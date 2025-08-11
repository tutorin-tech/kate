"""Implementation of the WebSocket protocol."""

import abc
import asyncio
import base64
import hashlib
import logging
import os
import sys
import struct

from kate.server.escape import utf8, native_str, to_unicode
from kate.server import gen, httputil, web, escape
from kate.server.iostream import StreamClosedError, IOStream
from kate.server.util import _websocket_mask

from typing import (
    cast,
    Any,
    Optional,
    Dict,
    Union,
    Callable,
)

LOGGER = logging.getLogger(__name__)


class WebSocketError(Exception):
    pass


class WebSocketClosedError(WebSocketError):
    """Raised by operations on a closed connection."""

    pass


class WebSocketHandler(web.RequestHandler):
    """Subclass this class to create a basic WebSocket handler."""

    def __init__(
        self,
        application: web.Application,
        request: httputil.HTTPServerRequest,
        **kwargs: Any,
    ) -> None:
        super().__init__(application, request, **kwargs)
        self.ws_connection = None  # type: Optional[WebSocketProtocol]
        self.close_code = None  # type: Optional[int]
        self.close_reason = None  # type: Optional[str]
        self._on_close_called = False

    async def get(self, *args: Any, **kwargs: Any) -> None:
        self.open_args = args
        self.open_kwargs = kwargs

        self.ws_connection = self.get_websocket_protocol()
        await self.ws_connection.accept_connection(self)

    def write_message(
        self, message: Union[bytes, str, Dict[str, Any]], binary: bool = False
    ) -> "Future[None]":
        """Sends the given message to the client of this Web Socket."""
        if self.ws_connection is None or self.ws_connection.is_closing():
            raise WebSocketClosedError()
        if isinstance(message, dict):
            message = escape.json_encode(message)
        return self.ws_connection.write_message(message, binary=binary)

    def set_nodelay(self, value: bool) -> None:
        """Set the no-delay flag for this stream."""
        assert self.ws_connection is not None
        self.ws_connection.set_nodelay(value)

    def on_connection_close(self) -> None:
        if self.ws_connection:
            self.ws_connection.on_connection_close()
            self.ws_connection = None
        if not self._on_close_called:
            self._on_close_called = True
            self.on_close()

    def on_ws_connection_close(
        self, close_code: Optional[int] = None, close_reason: Optional[str] = None
    ) -> None:
        self.close_code = close_code
        self.close_reason = close_reason
        self.on_connection_close()

    def get_websocket_protocol(self) -> Optional["WebSocketProtocol"]:
        websocket_version = self.request.headers.get("Sec-WebSocket-Version")
        if websocket_version in ("7", "8", "13"):
            return WebSocketProtocol13(self, False)
        return None

    def _detach_stream(self) -> IOStream:
        # disable non-WS methods
        for method in [
            "write",
            "redirect",
            "set_header",
            "set_cookie",
            "set_status",
            "flush",
            "finish",
        ]:
            setattr(self, method, _raise_not_supported_for_websockets)
        return self.detach()


def _raise_not_supported_for_websockets(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("Method not supported for Web Sockets")


class WebSocketProtocol(abc.ABC):
    """Base class for WebSocket protocol versions."""

    def __init__(self, handler: "_WebSocketDelegate") -> None:
        self.handler = handler
        self.stream = None  # type: Optional[IOStream]
        self.client_terminated = False
        self.server_terminated = False

    def _run_callback(
        self, callback: Callable, *args: Any, **kwargs: Any
    ) -> "Optional[Future[Any]]":
        """Runs the given callback with exception handling.

        If the callback is a coroutine, returns its Future. On error, aborts the
        websocket connection and returns None.
        """
        try:
            result = callback(*args, **kwargs)
        except Exception:
            LOGGER.error(*sys.exc_info())
            self._abort()
            return None
        else:
            if result is not None:
                result = gen.convert_yielded(result)
                assert self.stream is not None
                self.stream.io_loop.add_future(result, lambda f: f.result())
            return result

    def on_connection_close(self) -> None:
        self._abort()

    def _abort(self) -> None:
        """Instantly aborts the WebSocket connection by closing the socket"""
        self.client_terminated = True
        self.server_terminated = True
        if self.stream is not None:
            self.stream.close()  # forcibly tear down the connection
        self.close()  # let the subclass cleanup


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

    stream = None  # type: IOStream

    def __init__(
        self,
        handler: "_WebSocketDelegate",
        mask_outgoing: bool,
    ) -> None:
        WebSocketProtocol.__init__(self, handler)
        self.mask_outgoing = mask_outgoing
        self._final_frame = False
        self._frame_opcode = None
        self._masked_frame = None
        self._frame_mask = None  # type: Optional[bytes]
        self._frame_length = None
        self._fragmented_message_buffer = None  # type: Optional[bytearray]
        self._fragmented_message_opcode = None
        self._waiting = None  # type: object
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

    async def accept_connection(self, handler: WebSocketHandler) -> None:
        try:
            self._handle_websocket_headers(handler)
        except ValueError:
            handler.set_status(400)
            log_msg = "Missing/Invalid WebSocket headers"
            handler.finish(log_msg)
            LOGGER.debug(log_msg)
            return

        try:
            await self._accept_connection(handler)
        except asyncio.CancelledError:
            self._abort()
            return
        except ValueError:
            LOGGER.debug("Malformed WebSocket request received", exc_info=True)
            self._abort()
            return

    def _handle_websocket_headers(self, handler: WebSocketHandler) -> None:
        """Verifies all invariant- and required headers

        If a header is missing or have an incorrect value ValueError will be
        raised
        """
        fields = ("Host", "Sec-Websocket-Key", "Sec-Websocket-Version")
        if not all(map(lambda f: handler.request.headers.get(f), fields)):
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
            cast(str, handler.request.headers.get("Sec-Websocket-Key"))
        )

    async def _accept_connection(self, handler: WebSocketHandler) -> None:
        handler.clear_header("Content-Type")
        handler.set_status(101)
        handler.set_header("Upgrade", "websocket")
        handler.set_header("Connection", "Upgrade")
        handler.set_header("Sec-WebSocket-Accept", self._challenge_response(handler))
        handler.finish()

        self.stream = handler._detach_stream()

        try:
            open_result = handler.open(*handler.open_args, **handler.open_kwargs)
            if open_result is not None:
                await open_result
        except Exception:
            LOGGER.error(*sys.exc_info())
            self._abort()
            return

        await self._receive_frame_loop()

    def _write_frame(
        self, fin: bool, opcode: int, data: bytes, flags: int = 0
    ) -> "Future[None]":
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
        return self.stream.write(frame)

    def write_message(
        self, message: Union[str, bytes, Dict[str, Any]], binary: bool = False
    ) -> "Future[None]":
        """Sends the given message to the client of this Web Socket."""
        if binary:
            opcode = 0x2
        else:
            opcode = 0x1
        if isinstance(message, dict):
            message = escape.json_encode(message)
        message = escape.utf8(message)
        assert isinstance(message, bytes)
        self._message_bytes_out += len(message)
        flags = 0
        # For historical reasons, write methods in Tornado operate in a semi-synchronous
        # mode in which awaiting the Future they return is optional (But errors can
        # still be raised). This requires us to go through an awkward dance here
        # to transform the errors that may be returned while presenting the same
        # semi-synchronous interface.
        try:
            fut = self._write_frame(True, opcode, message, flags=flags)
        except StreamClosedError:
            raise WebSocketClosedError()

        async def wrapper() -> None:
            try:
                await fut
            except StreamClosedError:
                raise WebSocketClosedError()

        return asyncio.ensure_future(wrapper())

    async def _receive_frame_loop(self) -> None:
        try:
            while not self.client_terminated:
                await self._receive_frame()
        except StreamClosedError:
            self._abort()
        self.handler.on_ws_connection_close(self.close_code, self.close_reason)

    async def _read_bytes(self, n: int) -> bytes:
        data = await self.stream.read_bytes(n)
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
        if reserved_bits:
            # client is using as-yet-undefined extensions; abort
            self._abort()
            return
        is_masked = bool(mask_payloadlen & 0x80)
        payloadlen = mask_payloadlen & 0x7F

        # Parse and validate the length.
        if opcode_is_control and payloadlen >= 126:
            # control frames must have payload < 126
            self._abort()
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
                self._abort()
                return
        elif opcode == 0:  # continuation frame
            if self._fragmented_message_buffer is None:
                # nothing to continue
                self._abort()
                return
            self._fragmented_message_buffer.extend(data)
            if is_final_frame:
                opcode = self._fragmented_message_opcode
                data = bytes(self._fragmented_message_buffer)
                self._fragmented_message_buffer = None
        else:  # start of new data message
            if self._fragmented_message_buffer is not None:
                # can't start new message until the old one is finished
                self._abort()
                return
            if not is_final_frame:
                self._fragmented_message_opcode = opcode
                self._fragmented_message_buffer = bytearray(data)

        if is_final_frame:
            handled_future = self._handle_message(opcode, data)
            if handled_future is not None:
                await handled_future

    def _handle_message(self, opcode: int, data: bytes) -> "Optional[Future[None]]":
        """Execute on_message, returning its Future if it is a coroutine."""
        if self.client_terminated:
            return None

        if opcode == 0x1:
            # UTF-8 data
            self._message_bytes_in += len(data)
            try:
                decoded = data.decode("utf-8")
            except UnicodeDecodeError:
                self._abort()
                return None
            return self._run_callback(self.handler.on_message, decoded)
        elif opcode == 0x2:
            # Binary data
            self._message_bytes_in += len(data)
            return self._run_callback(self.handler.on_message, data)
        elif opcode == 0x8:
            # Close
            self.client_terminated = True
            if len(data) >= 2:
                self.close_code = struct.unpack(">H", data[:2])[0]
            if len(data) > 2:
                self.close_reason = to_unicode(data[2:])
            # Echo the received close code, if any (RFC 6455 section 5.5.1).
            self.close(self.close_code)
        else:
            self._abort()
        return None

    def close(self, code: Optional[int] = None, reason: Optional[str] = None) -> None:
        """Closes the WebSocket connection."""
        if not self.server_terminated:
            if not self.stream.closed():
                if code is None and reason is not None:
                    code = 1000  # "normal closure" status code
                if code is None:
                    close_data = b""
                else:
                    close_data = struct.pack(">H", code)
                if reason is not None:
                    close_data += utf8(reason)
                try:
                    self._write_frame(True, 0x8, close_data)
                except StreamClosedError:
                    self._abort()
            self.server_terminated = True
        if self.client_terminated:
            if self._waiting is not None:
                self.stream.io_loop.remove_timeout(self._waiting)
                self._waiting = None
            self.stream.close()
        elif self._waiting is None:
            # Give the client a few seconds to complete a clean shutdown,
            # otherwise just close the connection.
            self._waiting = self.stream.io_loop.add_timeout(
                self.stream.io_loop.time() + 5, self._abort
            )

    def is_closing(self) -> bool:
        """Return ``True`` if this connection is closing.

        The connection is considered closing if either side has
        initiated its closing handshake or if the stream has been
        shut down uncleanly.
        """
        return self.stream.closed() or self.client_terminated or self.server_terminated

    def set_nodelay(self, x: bool) -> None:
        self.stream.set_nodelay(x)
