"""Implementation of the WebSocket protocol.

`WebSockets <http://dev.w3.org/html5/websockets/>`_ allow for bidirectional
communication between the browser and server. WebSockets are supported in the
current versions of all major browsers.

This module implements the final version of the WebSocket protocol as
defined in `RFC 6455 <http://tools.ietf.org/html/rfc6455>`_.
"""

import abc
import asyncio
import base64
import contextlib
import hashlib
import logging
import os
import socket
import struct
import zlib
import time

from urllib.parse import urlparse

from kate.core.escape import to_unicode, json_encode, utf8, native_str
from kate.core.util import _websocket_mask_python as _websocket_mask
from kate.core import httputil, server

from typing import (
    TYPE_CHECKING,
    cast,
    Any,
    Optional,
    Dict,
    Union,
    List,
    Awaitable,
    Tuple,
)

if TYPE_CHECKING:
    from typing_extensions import Protocol

    from kate.core.server import BaseServer

    # The zlib compressor types aren't actually exposed anywhere
    # publicly, so declare protocols for the portions we use.
    class _Compressor(Protocol):
        def compress(self, data: bytes) -> bytes:
            pass

        def flush(self, mode: int) -> bytes:
            pass

    class _Decompressor(Protocol):
        unconsumed_tail = b""  # type: bytes

        def decompress(self, data: bytes, max_length: int) -> bytes:
            pass

    class _WebSocketDelegate(Protocol):
        # The common base interface implemented by WebSocketHandler on
        # the server side and WebSocketClientConnection on the client
        # side.
        async def on_ws_connection_close(
            self, close_code: Optional[int] = None, close_reason: Optional[str] = None
        ) -> None:
            pass

        def on_message(self, message: Union[str, bytes]) -> Optional["Awaitable[None]"]:
            pass

        async def on_ping(self, data: bytes) -> None:
            pass

        async def on_pong(self, data: bytes) -> None:
            pass


_default_max_message_size = 10 * 1024 * 1024

# Python's GzipFile defaults to level 9, while most other gzip
# tools (including gzip itself) default to 6, which is probably a
# better CPU/size tradeoff.
GZIP_LEVEL = 6

LOGGER = logging.getLogger(__name__)

class WebSocketError(Exception):
    pass


class WebSocketClosedError(WebSocketError):
    """Raised by operations on a closed connection."""

    pass


class _DecompressTooLargeError(Exception):
    pass


class _WebSocketParams:
    def __init__(
        self,
        ping_interval: Optional[float] = None,
        ping_timeout: Optional[float] = None,
        max_message_size: int = _default_max_message_size,
        compression_options: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.max_message_size = max_message_size
        self.compression_options = compression_options


class WebSocketHandler:
    """Subclass this class to create a basic WebSocket handler.

    Override `on_message` to handle incoming messages, and use
    `write_message` to send messages to the client. You can also
    override `open` and `on_close` to handle opened and closed
    connections.

    See http://dev.w3.org/html5/websockets/ for details on the
    JavaScript interface.  The protocol is specified at
    http://tools.ietf.org/html/rfc6455.

    Here is an example WebSocket handler that echos back all received messages
    back to the client:

    .. testcode::

      class EchoWebSocket(WebSocketHandler):
          def open(self):
              print("WebSocket opened")

          def on_message(self, message):
              self.write_message(u"You said: " + message)

          def on_close(self):
              print("WebSocket closed")

    WebSockets are not standard HTTP connections. The "handshake" is
    HTTP, but after the handshake, the protocol is
    message-based. The only communication methods available to you are
    `write_message()`, `ping()`, and `close()`. Likewise, your request
    handler class should implement `open()` method rather than
    ``get()`` or ``post()``.

    If you map the handler above to ``/websocket`` in your application, you can
    invoke it in JavaScript with::

      var ws = new WebSocket("ws://localhost:8888/websocket");
      ws.onopen = function() {
         ws.send("Hello, world");
      };
      ws.onmessage = function (evt) {
         alert(evt.data);
      };

    This script pops up an alert box that says "You said: Hello, world".

    Web browsers allow any site to open a websocket connection to any other,
    instead of using the same-origin policy that governs other network
    access from JavaScript.  This can be surprising and is a potential
    security hole, so since Tornado 4.0 `WebSocketHandler` requires
    applications that wish to receive cross-origin websockets to opt in
    by overriding the `~WebSocketHandler.check_origin` method (see that
    method's docs for details).  Failure to do so is the most likely
    cause of 403 errors when making a websocket connection.

    When using a secure websocket connection (``wss://``) with a self-signed
    certificate, the connection from a browser may fail because it wants
    to show the "accept this certificate" dialog but has nowhere to show it.
    You must first visit a regular HTML page using the same certificate
    to accept it before the websocket connection will succeed.

    If the application setting ``websocket_ping_interval`` has a non-zero
    value, a ping will be sent periodically, and the connection will be
    closed if a response is not received before the ``websocket_ping_timeout``.
    Both settings are in seconds; floating point values are allowed.
    The default timeout is equal to the interval.

    Messages larger than the ``websocket_max_message_size`` application setting
    (default 10MiB) will not be accepted.
    """

    settings = {}

    def __init__(
        self,
        headers: Dict[str, Any],
        reader: "asyncio.StreamReader",
        writer: "asyncio.StreamWriter",
        server: "BaseServer",
    ) -> None:
        self.ws_connection = None  # type: Optional[WebSocketProtocol]
        self.close_code = None  # type: Optional[int]
        self.close_reason = None  # type: Optional[str]
        self._on_close_called = False

        self._reader = reader
        self._writer = writer
        self.server = server
        self.headers = headers

    async def get(self, *args: 'Any', **kwargs: 'Any') -> None:
        self.open_args = args
        self.open_kwargs = kwargs

        # Upgrade header should be present and should be equal to WebSocket
        if self.headers.get("Upgrade", "").lower() != "websocket":
            log_msg = 'Can "Upgrade" only to "WebSocket".'
            LOGGER.debug(log_msg)
            return await self.server.send_http_error(self._writer, 400, log_msg)

        # Connection header should be upgrade.
        # Some proxy servers/load balancers
        # might mess with it.
        headers = self.headers
        connection = map(
            lambda s: s.strip().lower(), headers.get("Connection", "").split(",")
        )
        if "upgrade" not in connection:
            log_msg = '"Connection" must be "Upgrade".'
            LOGGER.debug(log_msg)
            return await self.server.send_http_error(self._writer, 400, log_msg)

        # Handle WebSocket Origin naming convention differences
        # The difference between version 8 and 13 is that in 8 the
        # client sends a "Sec-Websocket-Origin" header and in 13 it's
        # simply "Origin".
        if "Origin" in self.headers:
            origin = self.headers.get("Origin")
        else:
            origin = self.headers.get("Sec-Websocket-Origin", None)

        # If there was an origin header, check to make sure it matches
        # according to check_origin. When the origin is None, we assume it
        # did not come from a browser and that it can be passed on.
        if origin is not None and not self.check_origin(origin):
            log_msg = "Cross origin websockets not allowed"
            LOGGER.debug(log_msg)
            return await self.server.send_http_error(self._writer, 403, log_msg)

        self.ws_connection = self.get_websocket_protocol()
        if self.ws_connection:
            return await self.ws_connection.accept_connection(self)

        return await self.server.send_http_error(
            self._writer,
            code=426,
            message="Upgrade Required",
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Sec-WebSocket-Version": "7, 8, 13",
            }
        )

    @property
    def ping_interval(self) -> Optional[float]:
        """The interval for sending websocket pings.

        If this is non-zero, the websocket will send a ping every
        ping_interval seconds.
        The client will respond with a "pong". The connection can be configured
        to timeout on late pong delivery using ``websocket_ping_timeout``.

        Set ``websocket_ping_interval = 0`` to disable pings.

        Default: ``0``
        """
        return self.settings.get("websocket_ping_interval", None)

    @property
    def ping_timeout(self) -> Optional[float]:
        """Timeout if no pong is received in this many seconds.

        To be used in combination with ``websocket_ping_interval > 0``.
        If a ping response (a "pong") is not received within
        ``websocket_ping_timeout`` seconds, then the websocket connection
        will be closed.

        This can help to clean up clients which have disconnected without
        cleanly closing the websocket connection.

        Note, the ping timeout cannot be longer than the ping interval.

        Set ``websocket_ping_timeout = 0`` to disable the ping timeout.

        Default: equal to the ``ping_interval``.
        """
        return self.settings.get("websocket_ping_timeout", None)

    @property
    def max_message_size(self) -> int:
        """Maximum allowed message size.

        If the remote peer sends a message larger than this, the connection
        will be closed.

        Default is 10MiB.
        """
        return self.settings.get(
            "websocket_max_message_size", _default_max_message_size
        )

    async def write_message(
        self, message: Union[bytes, str, Dict[str, Any]], binary: bool = False,
    ) -> None:
        """Sends the given message to the client of this Web Socket.

        The message may be either a string or a dict (which will be
        encoded as json).  If the ``binary`` argument is false, the
        message will be sent as utf8; in binary mode any byte string
        is allowed.

        If the connection is already closed, raises `WebSocketClosedError`.
        Returns a `.Future` which can be used for flow control.
        """
        if self.ws_connection is None or self.ws_connection.is_closing():
            raise WebSocketClosedError()
        if isinstance(message, dict):
            message = json_encode(message)
        return await self.ws_connection.write_message(message, binary=binary)

    def select_subprotocol(self, subprotocols: List[str]) -> Optional[str]:
        """Override to implement subprotocol negotiation.

        ``subprotocols`` is a list of strings identifying the
        subprotocols proposed by the client.  This method may be
        overridden to return one of those strings to select it, or
        ``None`` to not select a subprotocol.

        Failure to select a subprotocol does not automatically abort
        the connection, although clients may close the connection if
        none of their proposed subprotocols was selected.

        The list may be empty, in which case this method must return
        None. This method is always called exactly once even if no
        subprotocols were proposed so that the handler can be advised
        of this fact.
        """
        return None

    @property
    def selected_subprotocol(self) -> Optional[str]:
        """The subprotocol returned by `select_subprotocol`."""
        assert self.ws_connection is not None
        return self.ws_connection.selected_subprotocol

    def get_compression_options(self) -> Optional[Dict[str, Any]]:
        """Override to return compression options for the connection.

        If this method returns None (the default), compression will
        be disabled.  If it returns a dict (even an empty one), it
        will be enabled.  The contents of the dict may be used to
        control the following compression options:

        ``compression_level`` specifies the compression level.

        ``mem_level`` specifies the amount of memory used for the internal compression state.

         These parameters are documented in detail here:
         https://docs.python.org/3.13/library/zlib.html#zlib.compressobj
        """
        # TODO: Add wbits option.
        return None

    async def open(self, *args: str, **kwargs: str) -> None:
        """Invoked when a new WebSocket is opened.

        The arguments to `open` are extracted from the `tornado.web.URLSpec`
        regular expression, just like the arguments to
        `tornado.web.RequestHandler.get`.

        `open` may be a coroutine. `on_message` will not be called until
        `open` has returned.
        """
        pass

    async def on_message(self, message: Union[str, bytes]) -> Optional[Awaitable[None]]:
        """Handle incoming messages on the WebSocket

        This method must be overridden.
        """
        raise NotImplementedError

    async def ping(self, data: Union[str, bytes] = b"") -> None:
        """Send ping frame to the remote end.

        The data argument allows a small amount of data (up to 125
        bytes) to be sent as a part of the ping message. Note that not
        all websocket implementations expose this data to
        applications.

        Consider using the ``websocket_ping_interval`` application
        setting instead of sending pings manually.
        """
        data = utf8(data)
        if self.ws_connection is None or self.ws_connection.is_closing():
            raise WebSocketClosedError()
        await self.ws_connection.write_ping(data)

    async def on_pong(self, data: bytes) -> None:
        """Invoked when the response to a ping frame is received."""
        pass

    async def on_ping(self, data: bytes) -> None:
        """Invoked when the a ping frame is received."""
        pass

    async def on_close(self) -> None:
        """Invoked when the WebSocket is closed.

        If the connection was closed cleanly and a status code or reason
        phrase was supplied, these values will be available as the attributes
        ``self.close_code`` and ``self.close_reason``.
        """
        pass

    async def close(self, code: Optional[int] = None, reason: Optional[str] = None) -> None:
        """Closes this Web Socket.

        Once the close handshake is successful the socket will be closed.

        ``code`` may be a numeric status code, taken from the values
        defined in `RFC 6455 section 7.4.1
        <https://tools.ietf.org/html/rfc6455#section-7.4.1>`_.
        ``reason`` may be a textual message about why the connection is
        closing.  These values are made available to the client, but are
        not otherwise interpreted by the websocket protocol.
        """
        if self.ws_connection:
            await self.ws_connection.close(code, reason)
            self.ws_connection = None

    def check_origin(self, origin: str) -> bool:
        """Override to enable support for allowing alternate origins.

        The ``origin`` argument is the value of the ``Origin`` HTTP
        header, the url responsible for initiating this request.  This
        method is not called for clients that do not send this header;
        such requests are always allowed (because all browsers that
        implement WebSockets support this header, and non-browser
        clients do not have the same cross-site security concerns).

        Should return ``True`` to accept the request or ``False`` to
        reject it. By default, rejects all requests with an origin on
        a host other than this one.

        This is a security protection against cross site scripting attacks on
        browsers, since WebSockets are allowed to bypass the usual same-origin
        policies and don't use CORS headers.

        .. warning::

           This is an important security measure; don't disable it
           without understanding the security implications. In
           particular, if your authentication is cookie-based, you
           must either restrict the origins allowed by
           ``check_origin()`` or implement your own XSRF-like
           protection for websocket connections. See `these
           <https://www.christian-schneider.net/CrossSiteWebSocketHijacking.html>`_
           `articles
           <https://devcenter.heroku.com/articles/websocket-security>`_
           for more.

        To accept all cross-origin traffic (which was the default prior to
        Tornado 4.0), simply override this method to always return ``True``::

            def check_origin(self, origin):
                return True

        To allow connections from any subdomain of your site, you might
        do something like::

            def check_origin(self, origin):
                parsed_origin = urllib.parse.urlparse(origin)
                return parsed_origin.netloc.endswith(".mydomain.com")

        """
        parsed_origin = urlparse(origin)
        origin = parsed_origin.netloc
        origin = origin.lower()

        host = self.headers.get("Host")

        # Check to see that origin matches host directly, including ports
        return origin == host

    def set_nodelay(self, value: bool) -> None:
        """Set the no-delay flag for this stream.

        By default, small messages may be delayed and/or combined to minimize
        the number of packets sent.  This can sometimes cause 200-500ms delays
        due to the interaction between Nagle's algorithm and TCP delayed
        ACKs.  To reduce this delay (at the expense of possibly increasing
        bandwidth usage), call ``self.set_nodelay(True)`` once the websocket
        connection is established.

        See `.BaseIOStream.set_nodelay` for additional details.
        """
        assert self.ws_connection is not None
        self.ws_connection.set_nodelay(value)

    async def on_connection_close(self) -> None:
        if self.ws_connection:
            await self.ws_connection.on_connection_close()
            self.ws_connection = None
        if not self._on_close_called:
            self._on_close_called = True
            await self.on_close()

    async def on_ws_connection_close(
        self, close_code: Optional[int] = None, close_reason: Optional[str] = None
    ) -> None:
        self.close_code = close_code
        self.close_reason = close_reason
        await self.on_connection_close()

    def get_websocket_protocol(self) -> Optional["WebSocketProtocol"]:
        websocket_version = self.headers.get("Sec-WebSocket-Version")
        if websocket_version in ("7", "8", "13"):
            params = _WebSocketParams(
                ping_interval=self.settings.get("ping_interval"),
                ping_timeout=self.settings.get("ping_timeout"),
                max_message_size=self.settings.get("max_message_size", _default_max_message_size),
                compression_options=self.get_compression_options(),
            )
            return WebSocketProtocol13(self, False, params, self._reader, self._writer)
        return None


class WebSocketProtocol(abc.ABC):
    """Base class for WebSocket protocol versions."""

    def __init__(
        self,
        handler: "_WebSocketDelegate",
        reader: "asyncio.StreamReader",
        writer: "asyncio.StreamWriter",
    ) -> None:
        self.handler = handler
        self.client_terminated = False
        self.server_terminated = False

        self._reader = reader
        self._writer = writer

    async def on_connection_close(self) -> None:
        await self._abort()

    async def _abort(self) -> None:
        """Instantly aborts the WebSocket connection by closing the socket"""
        self.client_terminated = True
        self.server_terminated = True

        self._writer.close()
        with contextlib.suppress(ConnectionResetError):
            await self._writer.wait_closed()
        await self.close()  # let the subclass cleanup

    @abc.abstractmethod
    async def close(self, code: Optional[int] = None, reason: Optional[str] = None) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def is_closing(self) -> bool:
        raise NotImplementedError()

    @abc.abstractmethod
    async def accept_connection(self, handler: WebSocketHandler) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    async def write_message(
        self, message: Union[str, bytes, Dict[str, Any]], binary: bool = False
    ) -> None:
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def selected_subprotocol(self) -> Optional[str]:
        raise NotImplementedError()

    @abc.abstractmethod
    async def write_ping(self, data: bytes) -> None:
        raise NotImplementedError()

    # The entry points below are used by WebSocketClientConnection,
    # which was introduced after we only supported a single version of
    # WebSocketProtocol. The WebSocketProtocol/WebSocketProtocol13
    # boundary is currently pretty ad-hoc.
    @abc.abstractmethod
    def _process_server_headers(
        self, key: Union[str, bytes], headers
    ) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def start_pinging(self) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    async def _receive_frame_loop(self) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def set_nodelay(self, value: bool) -> None:
        raise NotImplementedError()


class _PerMessageDeflateCompressor:
    def __init__(
        self,
        persistent: bool,
        max_wbits: Optional[int],
        compression_options: Optional[Dict[str, Any]] = None,
    ) -> None:
        if max_wbits is None:
            max_wbits = zlib.MAX_WBITS
        # There is no symbolic constant for the minimum wbits value.
        if not (8 <= max_wbits <= zlib.MAX_WBITS):
            raise ValueError(
                "Invalid max_wbits value %r; allowed range 8-%d",
                max_wbits,
                zlib.MAX_WBITS,
            )
        self._max_wbits = max_wbits

        if (
            compression_options is None
            or "compression_level" not in compression_options
        ):
            self._compression_level = GZIP_LEVEL
        else:
            self._compression_level = compression_options["compression_level"]

        if compression_options is None or "mem_level" not in compression_options:
            self._mem_level = 8
        else:
            self._mem_level = compression_options["mem_level"]

        if persistent:
            self._compressor = self._create_compressor()  # type: Optional[_Compressor]
        else:
            self._compressor = None

    def _create_compressor(self) -> "_Compressor":
        return zlib.compressobj(
            self._compression_level, zlib.DEFLATED, -self._max_wbits, self._mem_level
        )

    def compress(self, data: bytes) -> bytes:
        compressor = self._compressor or self._create_compressor()
        data = compressor.compress(data) + compressor.flush(zlib.Z_SYNC_FLUSH)
        assert data.endswith(b"\x00\x00\xff\xff")
        return data[:-4]


class _PerMessageDeflateDecompressor:
    def __init__(
        self,
        persistent: bool,
        max_wbits: Optional[int],
        max_message_size: int,
        compression_options: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._max_message_size = max_message_size
        if max_wbits is None:
            max_wbits = zlib.MAX_WBITS
        if not (8 <= max_wbits <= zlib.MAX_WBITS):
            raise ValueError(
                "Invalid max_wbits value %r; allowed range 8-%d",
                max_wbits,
                zlib.MAX_WBITS,
            )
        self._max_wbits = max_wbits
        if persistent:
            self._decompressor = (
                self._create_decompressor()
            )  # type: Optional[_Decompressor]
        else:
            self._decompressor = None

    def _create_decompressor(self) -> "_Decompressor":
        return zlib.decompressobj(-self._max_wbits)

    def decompress(self, data: bytes) -> bytes:
        decompressor = self._decompressor or self._create_decompressor()
        result = decompressor.decompress(
            data + b"\x00\x00\xff\xff", self._max_message_size
        )
        if decompressor.unconsumed_tail:
            raise _DecompressTooLargeError()
        return result


class WebSocketProtocol13(WebSocketProtocol):
    """Implementation of the WebSocket protocol from RFC 6455.

    This class supports versions 7 and 8 of the protocol in addition to the
    final version 13.
    """

    # Bit masks for the first byte of a frame.
    FIN = 0x80
    RSV1 = 0x40
    RSV2 = 0x20
    RSV3 = 0x10
    RSV_MASK = RSV1 | RSV2 | RSV3
    OPCODE_MASK = 0x0F

    def __init__(
        self,
        handler: "_WebSocketDelegate",
        mask_outgoing: bool,
        params: _WebSocketParams,
        reader: "asyncio.StreamReader",
        writer: "asyncio.StreamWriter",
    ) -> None:
        WebSocketProtocol.__init__(self, handler, reader, writer)
        self.mask_outgoing = mask_outgoing
        self.params = params
        self._final_frame = False
        self._frame_opcode = None
        self._masked_frame = None
        self._frame_mask = None  # type: Optional[bytes]
        self._frame_length = None
        self._fragmented_message_buffer = None  # type: Optional[bytearray]
        self._fragmented_message_opcode = None
        self._compression_options = params.compression_options
        self._decompressor = None  # type: Optional[_PerMessageDeflateDecompressor]
        self._compressor = None  # type: Optional[_PerMessageDeflateCompressor]
        self._frame_compressed = None  # type: Optional[bool]
        # The total uncompressed size of all messages received or sent.
        # Unicode messages are encoded to utf8.
        # Only for testing; subject to change.
        self._message_bytes_in = 0
        self._message_bytes_out = 0
        # The total size of all packets received or sent.  Includes
        # the effect of compression, frame overhead, and control frames.
        self._wire_bytes_in = 0
        self._wire_bytes_out = 0
        self._received_pong = False  # type: bool
        self.close_code = None  # type: Optional[int]
        self.close_reason = None  # type: Optional[str]
        self._ping_coroutine = None  # type: Optional[asyncio.Task]

    # Use a property for this to satisfy the abc.
    @property
    def selected_subprotocol(self) -> Optional[str]:
        return self._selected_subprotocol

    @selected_subprotocol.setter
    def selected_subprotocol(self, value: Optional[str]) -> None:
        self._selected_subprotocol = value

    async def accept_connection(self, handler: WebSocketHandler) -> None:
        try:
            self._handle_websocket_headers(handler)
        except ValueError:
            log_msg = "Missing/Invalid WebSocket headers"
            LOGGER.debug(log_msg)
            return await self.handler.server.send_http_error(self._writer, 400, log_msg)

        try:
            await self._accept_connection(handler)
        except asyncio.CancelledError:
            await self._abort()
            return None
        except ValueError:
            LOGGER.debug("Malformed WebSocket request received")
            await self._abort()
            return None

    def _handle_websocket_headers(self, handler: WebSocketHandler) -> None:
        """Verifies all invariant- and required headers

        If a header is missing or have an incorrect value ValueError will be
        raised
        """
        fields = ("Host", "Sec-WebSocket-Key", "Sec-WebSocket-Version")
        if not all(map(lambda field: handler.headers.get(field), fields)):
            raise ValueError("Missing/Invalid WebSocket headers")

    @staticmethod
    def compute_accept_value(key: Union[str, bytes]) -> str:
        """Computes the value for the Sec-WebSocket-Accept header,
        given the value for Sec-WebSocket-Key.
        """
        sha1 = hashlib.sha1()
        sha1.update(utf8(key))
        sha1.update(b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11")  # Magic value
        return native_str(base64.b64encode(sha1.digest()))

    def _challenge_response(self, handler: WebSocketHandler) -> str:
        return WebSocketProtocol13.compute_accept_value(
            cast(str, handler.headers.get("Sec-WebSocket-Key"))
        )

    async def _accept_connection(self, handler: WebSocketHandler) -> None:
        response = server.Response()
        subprotocol_header = handler.headers.get("Sec-WebSocket-Protocol")
        if subprotocol_header:
            subprotocols = [s.strip() for s in subprotocol_header.split(",")]
        else:
            subprotocols = []
        self.selected_subprotocol = handler.select_subprotocol(subprotocols)
        if self.selected_subprotocol:
            assert self.selected_subprotocol in subprotocols
            response.set_header("Sec-WebSocket-Protocol", self.selected_subprotocol)

        extensions = self._parse_extensions_header(handler.headers)
        for ext in extensions:
            if ext[0] == "permessage-deflate" and self._compression_options is not None:
                # TODO: negotiate parameters if compression_options
                # specifies limits.
                self._create_compressors("server", ext[1], self._compression_options)
                if (
                    "client_max_window_bits" in ext[1]
                    and ext[1]["client_max_window_bits"] is None
                ):
                    # Don't echo an offered client_max_window_bits
                    # parameter with no value.
                    del ext[1]["client_max_window_bits"]
                response.set_header(
                    "Sec-WebSocket-Extensions",
                    httputil._encode_header("permessage-deflate", ext[1]),
                )
                break

        response.clear_header("Content-Type")
        response.set_status(101)
        response.set_header("Upgrade", "websocket")
        response.set_header("Connection", "Upgrade")
        response.set_header("Sec-WebSocket-Accept", self._challenge_response(handler))
        self._writer.write(response.to_bytes())
        await self._writer.drain()

        self.start_pinging()
        try:
            await handler.open(*handler.open_args, **handler.open_kwargs)
        except Exception as exc:
            LOGGER.error(exc)
            await self._abort()
            return

        await self._receive_frame_loop()

    def _parse_extensions_header(
        self, headers,
    ) -> List[Tuple[str, Dict[str, str]]]:
        extensions = headers.get("Sec-WebSocket-Extensions", "")
        if extensions:
            return [httputil._parse_header(e.strip()) for e in extensions.split(",")]
        return []

    def _process_server_headers(
        self, key: Union[str, bytes], headers,
    ) -> None:
        """Process the headers sent by the server to this client connection.

        'key' is the websocket handshake challenge/response key.
        """
        assert headers["Upgrade"].lower() == "websocket"
        assert headers["Connection"].lower() == "upgrade"
        accept = self.compute_accept_value(key)
        assert headers["Sec-Websocket-Accept"] == accept

        extensions = self._parse_extensions_header(headers)
        for ext in extensions:
            if ext[0] == "permessage-deflate" and self._compression_options is not None:
                self._create_compressors("client", ext[1])
            else:
                raise ValueError("unsupported extension %r", ext)

        self.selected_subprotocol = headers.get("Sec-WebSocket-Protocol", None)

    def _get_compressor_options(
        self,
        side: str,
        agreed_parameters: Dict[str, Any],
        compression_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Converts a websocket agreed_parameters set to keyword arguments
        for our compressor objects.
        """
        options = dict(
            persistent=(side + "_no_context_takeover") not in agreed_parameters
        )  # type: Dict[str, Any]
        wbits_header = agreed_parameters.get(side + "_max_window_bits", None)
        if wbits_header is None:
            options["max_wbits"] = zlib.MAX_WBITS
        else:
            options["max_wbits"] = int(wbits_header)
        options["compression_options"] = compression_options
        return options

    def _create_compressors(
        self,
        side: str,
        agreed_parameters: Dict[str, Any],
        compression_options: Optional[Dict[str, Any]] = None,
    ) -> None:
        # TODO: handle invalid parameters gracefully
        allowed_keys = {
            "server_no_context_takeover",
            "client_no_context_takeover",
            "server_max_window_bits",
            "client_max_window_bits",
        }
        for key in agreed_parameters:
            if key not in allowed_keys:
                raise ValueError("unsupported compression parameter %r" % key)
        other_side = "client" if (side == "server") else "server"
        self._compressor = _PerMessageDeflateCompressor(
            **self._get_compressor_options(side, agreed_parameters, compression_options)
        )
        self._decompressor = _PerMessageDeflateDecompressor(
            max_message_size=self.params.max_message_size,
            **self._get_compressor_options(
                other_side, agreed_parameters, compression_options
            ),
        )

    async def _write_frame(
        self, fin: bool, opcode: int, data: bytes, flags: int = 0
    ) -> None:
        data_len = len(data)
        if opcode & 0x8:
            # All control frames MUST have a payload length of 125
            # bytes or less and MUST NOT be fragmented.
            if not fin:
                raise ValueError("control frames may not be fragmented")
            if data_len > 125:
                raise ValueError("control frame payloads may not exceed 125 bytes")
        if fin:
            finbit = self.FIN
        else:
            finbit = 0
        frame = struct.pack("B", finbit | opcode | flags)
        if self.mask_outgoing:
            mask_bit = 0x80
        else:
            mask_bit = 0
        if data_len < 126:
            frame += struct.pack("B", data_len | mask_bit)
        elif data_len <= 0xFFFF:
            frame += struct.pack("!BH", 126 | mask_bit, data_len)
        else:
            frame += struct.pack("!BQ", 127 | mask_bit, data_len)
        if self.mask_outgoing:
            mask = os.urandom(4)
            data = mask + _websocket_mask(mask, data)
        frame += data
        self._wire_bytes_out += len(frame)

        self._writer.write(frame)
        await self._writer.drain()

    async def write_message(
        self, message: Union[str, bytes, Dict[str, Any]], binary: bool = False
    ) -> None:
        """Sends the given message to the client of this Web Socket."""
        if binary:
            opcode = 0x2
        else:
            opcode = 0x1
        if isinstance(message, dict):
            message = json_encode(message)
        message = utf8(message)
        assert isinstance(message, bytes)
        self._message_bytes_out += len(message)
        flags = 0
        if self._compressor:
            message = self._compressor.compress(message)
            flags |= self.RSV1
        # For historical reasons, write methods in Tornado operate in a semi-synchronous
        # mode in which awaiting the Future they return is optional (But errors can
        # still be raised). This requires us to go through an awkward dance here
        # to transform the errors that may be returned while presenting the same
        # semi-synchronous interface.
        try:
            await self._write_frame(True, opcode, message, flags=flags)
        except ConnectionResetError:
            raise WebSocketClosedError()

    async def write_ping(self, data: bytes) -> None:
        """Send ping frame."""
        assert isinstance(data, bytes)
        await self._write_frame(True, 0x9, data)

    async def _receive_frame_loop(self) -> None:
        try:
            while not self.client_terminated:
                await self._receive_frame()
        except ConnectionResetError:
            await self._abort()
        await self.handler.on_ws_connection_close(self.close_code, self.close_reason)

    async def _read_bytes(self, n: int) -> bytes:
        data = await self._reader.readexactly(n)
        self._wire_bytes_in += n
        return data

    async def _receive_frame(self) -> None:
        # Read the frame header.
        data = await self._read_bytes(2)
        header, mask_payloadlen = struct.unpack("BB", data)
        is_final_frame = header & self.FIN
        reserved_bits = header & self.RSV_MASK
        opcode = header & self.OPCODE_MASK
        opcode_is_control = opcode & 0x8
        if self._decompressor is not None and opcode != 0:
            # Compression flag is present in the first frame's header,
            # but we can't decompress until we have all the frames of
            # the message.
            self._frame_compressed = bool(reserved_bits & self.RSV1)
            reserved_bits &= ~self.RSV1
        if reserved_bits:
            # client is using as-yet-undefined extensions; abort
            await self._abort()
            return
        is_masked = bool(mask_payloadlen & 0x80)
        payloadlen = mask_payloadlen & 0x7F

        # Parse and validate the length.
        if opcode_is_control and payloadlen >= 126:
            # control frames must have payload < 126
            await self._abort()
            return
        if payloadlen < 126:
            self._frame_length = payloadlen
        elif payloadlen == 126:
            data = await self._read_bytes(2)
            payloadlen = struct.unpack("!H", data)[0]
        elif payloadlen == 127:
            data = await self._read_bytes(8)
            payloadlen = struct.unpack("!Q", data)[0]
        new_len = payloadlen
        if self._fragmented_message_buffer is not None:
            new_len += len(self._fragmented_message_buffer)
        if new_len > self.params.max_message_size:
            await self.close(1009, "message too big")
            await self._abort()
            return

        # Read the payload, unmasking if necessary.
        if is_masked:
            self._frame_mask = await self._read_bytes(4)
        data = await self._read_bytes(payloadlen)
        if is_masked:
            assert self._frame_mask is not None
            data = _websocket_mask(self._frame_mask, data)

        # Decide what to do with this frame.
        if opcode_is_control:
            # control frames may be interleaved with a series of fragmented
            # data frames, so control frames must not interact with
            # self._fragmented_*
            if not is_final_frame:
                # control frames must not be fragmented
                await self._abort()
                return
        elif opcode == 0:  # continuation frame
            if self._fragmented_message_buffer is None:
                # nothing to continue
                await self._abort()
                return
            self._fragmented_message_buffer.extend(data)
            if is_final_frame:
                opcode = self._fragmented_message_opcode
                data = bytes(self._fragmented_message_buffer)
                self._fragmented_message_buffer = None
        else:  # start of new data message
            if self._fragmented_message_buffer is not None:
                # can't start new message until the old one is finished
                await self._abort()
                return
            if not is_final_frame:
                self._fragmented_message_opcode = opcode
                self._fragmented_message_buffer = bytearray(data)

        if is_final_frame:
            handled_future = self._handle_message(opcode, data)
            if handled_future is not None:
                await handled_future

    async def _handle_message(self, opcode: int, data: bytes) -> "Optional[Future[None]]":
        """Execute on_message, returning its Future if it is a coroutine."""
        if self.client_terminated:
            return None

        if self._frame_compressed:
            assert self._decompressor is not None
            try:
                data = self._decompressor.decompress(data)
            except _DecompressTooLargeError:
                await self.close(1009, "message too big after decompression")
                await self._abort()
                return None

        if opcode == 0x1:
            # UTF-8 data
            self._message_bytes_in += len(data)
            try:
                decoded = data.decode("utf-8")
            except UnicodeDecodeError:
                await self._abort()
                return None
            return await self.handler.on_message(decoded)
        elif opcode == 0x2:
            # Binary data
            self._message_bytes_in += len(data)
            return await self.handler.on_message(data)
        elif opcode == 0x8:
            # Close
            self.client_terminated = True
            if len(data) >= 2:
                self.close_code = struct.unpack(">H", data[:2])[0]
            if len(data) > 2:
                self.close_reason = to_unicode(data[2:])
            # Echo the received close code, if any (RFC 6455 section 5.5.1).
            await self.close(self.close_code)
        elif opcode == 0x9:
            # Ping
            try:
                await self._write_frame(True, 0xA, data)
            except ConnectionResetError:
                await self._abort()
            await self.handler.on_ping(data)
        elif opcode == 0xA:
            # Pong
            self._received_pong = True
            return await self.handler.on_pong(data)
        else:
            await self._abort()
        return None

    async def close(self, code: Optional[int] = None, reason: Optional[str] = None) -> None:
        """Closes the WebSocket connection."""
        if not self.server_terminated:
            if not self._writer.is_closing():
                if code is None and reason is not None:
                    code = 1000  # "normal closure" status code
                if code is None:
                    close_data = b""
                else:
                    close_data = struct.pack(">H", code)
                if reason is not None:
                    close_data += utf8(reason)
                try:
                    await self._write_frame(True, 0x8, close_data)
                except ConnectionResetError:
                    await self._abort()
            self.server_terminated = True
        if self.client_terminated:
            self._writer.close()
            with contextlib.suppress(ConnectionResetError):
                await self._writer.wait_closed()
        if self._ping_coroutine:
            self._ping_coroutine.cancel()
            self._ping_coroutine = None

    def is_closing(self) -> bool:
        """Return ``True`` if this connection is closing.

        The connection is considered closing if either side has
        initiated its closing handshake or if the stream has been
        shut down uncleanly.
        """
        return self._writer.is_closing() or self.client_terminated or self.server_terminated

    def set_nodelay(self, value: bool) -> None:
        if self.handler.server.socket is not None and self.handler.server.socket.family in (
            socket.AF_INET,
            socket.AF_INET6,
        ):
            self.handler.server.socket.setsockopt(
                socket.IPPROTO_TCP, socket.TCP_NODELAY, 1 if value else 0
            )

    @property
    def ping_interval(self) -> float:
        interval = self.params.ping_interval
        if interval is not None:
            return interval
        return 0

    @property
    def ping_timeout(self) -> float:
        timeout = self.params.ping_timeout
        if timeout is not None:
            if self.ping_interval and timeout > self.ping_interval:
                LOGGER.warning(
                    # Note: using de_dupe_gen_log to prevent this message from
                    # being duplicated for each connection
                    f"The websocket_ping_timeout ({timeout}) cannot be longer"
                    f" than the websocket_ping_interval ({self.ping_interval})."
                    f"\nSetting websocket_ping_timeout={self.ping_interval}",
                )
                return self.ping_interval
            return timeout
        return self.ping_interval

    def start_pinging(self) -> None:
        """Start sending periodic pings to keep the connection alive"""
        if (
            # prevent multiple ping coroutines being run in parallel
            not self._ping_coroutine
            # only run the ping coroutine if a ping interval is configured
            and self.ping_interval > 0
        ):
            self._ping_coroutine = asyncio.create_task(self.periodic_ping())

    @staticmethod
    def ping_sleep_time(*, last_ping_time: float, interval: float, now: float) -> float:
        """Calculate the sleep time until the next ping should be sent."""
        return max(0, last_ping_time + interval - now)

    async def periodic_ping(self) -> None:
        """Send a ping and wait for a pong if ping_timeout is configured.

        Called periodically if the websocket_ping_interval is set and non-zero.
        """
        interval = self.ping_interval
        timeout = self.ping_timeout

        await asyncio.sleep(interval)

        while True:
            # send a ping
            self._received_pong = False
            ping_time = time.time()
            await self.write_ping(b"")

            # wait until the ping timeout
            await asyncio.sleep(timeout)

            # make sure we received a pong within the timeout
            if timeout > 0 and not self._received_pong:
                await self.close(reason="ping timed out")
                return

            # wait until the next scheduled ping
            await asyncio.sleep(
                self.ping_sleep_time(
                    last_ping_time=ping_time,
                    interval=interval,
                    now=time.time(),
                )
            )
