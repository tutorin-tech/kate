"""The module contains a base implementation of the websocket."""

import asyncio
import datetime
import json
import logging
import numbers
import re
import time
from http.client import responses
from typing import (
    List,
    Optional,
    Union,
)
from urllib.parse import urlparse

import tornado

from kate.core.exceptions import WebSocketClosedError
from kate.core.websocket import httputil
from kate.core.websocket.escape import to_unicode
from kate.core.websocket.mixins import CompressionMixin
from kate.core.websocket.protocol import WebSocketProtocol13

_default_max_message_size = 10 * 1024 * 1024

LOGGER = logging.getLogger(__name__)


class _WebSocketParams:
    def __init__(
        self,
        ping_interval: float | None = None,
        ping_timeout: float | None = None,
        max_message_size: int = _default_max_message_size,
        compression_options: 'dict[str, Any] | None' = None,
    ) -> None:
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.max_message_size = max_message_size
        self.compression_options = compression_options


async def _send_http_error(writer, code, message):
    body = message.encode()
    response = (
        f'HTTP/1.1 {code} {message}\r\n'
        f'Content-Type: text/plain\r\n'
        f'Content-Length: {len(body)}\r\n'
        f'\r\n'
    ).encode() + body

    writer.write(response)
    await writer.drain()
    writer.close()
    await writer.wait_closed()


class WebSocketHandler:
    """The class represents a base class for handling WebSocket connections."""

    settings = {}

    def __init__(
        self,
        headers,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):

        self._reader = reader
        self._writer = writer

        self._headers_written = False
        self._finished = False
        self._auto_finish = True
        self._prepared_future = None
        self.clear()

        self._finished = False
        self._on_close_called = False
        self.headers = headers
        self.ws_connection = None
        self.close_code = None
        self.close_reason = None

    async def get(self, *args: 'Any', **kwargs: 'Any'):
        # Handle WebSocket Origin naming convention differences
        # The difference between version 8 and 13 is that in 8 the
        # client sends a "Sec-Websocket-Origin" header and in 13 it's
        # simply "Origin".
        origin = self.headers.get('Origin') or self.headers.get('Sec-WebSocket-Origin')
        if origin is not None and not self.check_origin(origin):
            return await _send_http_error(
                self._writer,
                403,
                'Cross origin websockets not allowed',
            )

        self.ws_connection = self.get_websocket_protocol()
        if self.ws_connection:
            await self.ws_connection.accept_connection(self.headers, self)
        else:
            await _send_http_error(
                self._writer,
                426,
                'Upgrade Required',
            )

    async def close(self, code=None, reason=None):
        if self.ws_connection:
            self.ws_connection.close(code, reason)
            self.ws_connection = None

    def get_websocket_protocol(self):
        websocket_version = self.headers.get("Sec-WebSocket-Version")
        if websocket_version in ("7", "8", "13"):
            params = _WebSocketParams(
                ping_interval=self.settings.get('ping_interval'),
                ping_timeout=self.settings.get('ping_timeout'),
                max_message_size=self.settings.get('max_message_size', _default_max_message_size),
                compression_options=self.get_compression_options(),
            )
            return WebSocketProtocol13(self, False, params, self._reader, self._writer)
        return None

    async def on_message(self, message):
        """Handle incoming message from client."""
        pass

    def ping(self, data= b"") -> None:
        """Send ping frame to the remote end.

        The data argument allows a small amount of data (up to 125
        bytes) to be sent as a part of the ping message. Note that not
        all websocket implementations expose this data to
        applications.

        Consider using the ``websocket_ping_interval`` application
        setting instead of sending pings manually.

           The data argument is now optional.

        """
        if self.ws_connection is None or self.ws_connection.is_closing():
            raise WebSocketClosedError()

        self.ws_connection.write_ping(data)

    def on_pong(self, data: bytes) -> None:
        """Invoked when the response to a ping frame is received."""
        pass

    def on_ping(self, data: bytes) -> None:
        """Invoked when the a ping frame is received."""
        pass

    def on_close(self) -> None:
        """Invoked when the WebSocket is closed."""
        pass

    async def open(self):
        """Called when new WebSocket connection is opened."""

    async def write_message(self, message: str, binary=False):
        """Send a message to the client."""
        if self.ws_connection is None or self.ws_connection.is_closing():
            raise WebSocketClosedError()

        if isinstance(message, dict):
            message = json.dumps(message).replace("</", "<\\/")

        return await self.ws_connection.write_message(message, binary=binary)

    @property
    def ping_interval(self):
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
    def ping_timeout(self):
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

    def select_subprotocol(self, subprotocols):
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
    def selected_subprotocol(self):
        """The subprotocol returned by `select_subprotocol`."""
        assert self.ws_connection is not None
        return self.ws_connection.selected_subprotocol

    def get_compression_options(self):
        """Override to return compression options for the connection.

        If this method returns None (the default), compression will
        be disabled.  If it returns a dict (even an empty one), it
        will be enabled.  The contents of the dict may be used to
        control the following compression options:

        ``compression_level`` specifies the compression level.

        ``mem_level`` specifies the amount of memory used for the internal compression state.

           Added ``compression_level`` and ``mem_level``.
        """
        # TODO: Add wbits option.
        return None

    async def on_connection_close(self) -> None:
        if self.ws_connection:
            await self.ws_connection.on_connection_close()
            self.ws_connection = None

        if not self._on_close_called:
            self._on_close_called = True
            self.on_close()

    async def on_ws_connection_close(
        self, close_code = None, close_reason = None
    ) -> None:
        self.close_code = close_code
        self.close_reason = close_reason
        await self.on_connection_close()

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

    # https://www.rfc-editor.org/rfc/rfc9110#name-field-values
    _VALID_HEADER_CHARS = re.compile(r"[\x09\x20-\x7e\x80-\xff]*")

    def clear(self) -> None:
        """Resets all headers and content for this response."""
        self._headers = httputil.HTTPHeaders(
            {
                "Server": "TornadoServer/%s" % tornado.version,
                "Content-Type": "text/html; charset=UTF-8",
                "Date": httputil.format_timestamp(time.time()),
            }
        )
        self._write_buffer = []  # type: List[bytes]
        self._status_code = 200
        self._reason = httputil.responses[200]

    def _convert_header_value(self, value) -> str:
        # Convert the input value to a str. This type check is a bit
        # subtle: The bytes case only executes on python 3, and the
        # unicode case only executes on python 2, because the other
        # cases are covered by the first match for str.
        if isinstance(value, str):
            retval = value
        elif isinstance(value, bytes):
            # Non-ascii characters in headers are not well supported,
            # but if you pass bytes, use latin1 so they pass through as-is.
            retval = value.decode("latin1")
        elif isinstance(value, numbers.Integral):
            # return immediately since we know the converted value will be safe
            return str(value)
        elif isinstance(value, datetime.datetime):
            return httputil.format_timestamp(value)
        else:
            raise TypeError("Unsupported header value %r" % value)
        # If \n is allowed into the header, it is possible to inject
        # additional headers or split the request.
        if self._VALID_HEADER_CHARS.fullmatch(retval) is None:
            raise ValueError("Unsafe header value %r", retval)
        return retval

    def _clear_representation_headers(self) -> None:
        # 304 responses should not contain representation metadata
        # headers (defined in
        # https://tools.ietf.org/html/rfc7231#section-3.1)
        # not explicitly allowed by
        # https://tools.ietf.org/html/rfc7232#section-4.1
        headers = ["Content-Encoding", "Content-Language", "Content-Type"]
        for h in headers:
            self.clear_header(h)

    def set_status(self, status_code: int, reason: Optional[str] = None) -> None:
        """Sets the status code for our response.

        :arg int status_code: Response status code.
        :arg str reason: Human-readable reason phrase describing the status
            code. If ``None``, it will be filled in from
            `http.client.responses` or "Unknown".

           No longer validates that the response code is in
           `http.client.responses`.
        """
        self._status_code = status_code
        if reason is not None:
            self._reason = to_unicode(reason)
        else:
            self._reason = responses.get(status_code, "Unknown")

    def set_header(self, name: str, value) -> None:
        """Sets the given response header name and value.

        All header values are converted to strings (`datetime` objects
        are formatted according to the HTTP specification for the
        ``Date`` header).

        """
        self._headers[name] = self._convert_header_value(value)

    async def finish(self, chunk: Optional[Union[str, bytes, dict]] = None) -> "Future[None]":
        """Finishes this response, ending the HTTP request.

        Passing a ``chunk`` to ``finish()`` is equivalent to passing that
        chunk to ``write()`` and then calling ``finish()`` with no arguments.

        Returns a `.Future` which may optionally be awaited to track the sending
        of the response to the client. This `.Future` resolves when all the response
        data has been sent, and raises an error if the connection is closed before all
        data can be sent.

           Now returns a `.Future` instead of ``None``.
        """
        if self._finished:
            raise RuntimeError("finish() called twice")

        if chunk is not None:
            self._writer.write(chunk.encode('utf-8'))
            await self._writer.drain()
            self._writer.close()
            await self._writer.wait_closed()

        self._finished = True

    def clear_header(self, name: str) -> None:
        """Clears an outgoing header, undoing a previous `set_header` call.

        Note that this method does not apply to multi-valued headers
        set by `add_header`.
        """
        if name in self._headers:
            del self._headers[name]
