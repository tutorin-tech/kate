import abc
import asyncio
import base64
import hashlib
import os
import struct
import logging
import time

from kate.core.websocket import CompressionMixin, httputil
from kate.core.exceptions import WebSocketClosedError, _DecompressTooLargeError
from kate.core.websocket.escape import utf8, to_unicode, json_encode

# This is the Globally Unique Identifier (GUID) specified in RFC 6455 (WebSocket Protocol).
# It is concatenated with the Sec-WebSocket-Key header value to compute
# the Sec-WebSocket-Accept response.
# See RFC 6455 Section 1.3 (https://tools.ietf.org/html/rfc6455#section-1.3).
_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

LOGGER = logging.getLogger(__name__)


class StreamClosedError(IOError):
    """Exception raised by `IOStream` methods when the stream is closed.

    Note that the close callback is scheduled to run *after* other
    callbacks on the stream (to allow for buffered data to be processed),
    so you may see this error before you see the close callback.

    The ``real_error`` attribute contains the underlying error that caused
    the stream to close (if any).
    """


async def _send_http_error(writer, code, message):
    body = message.encode()
    response = b'HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\n\r\nFile not found'

    writer.write(response)
    await writer.drain()
    writer.close()
    await writer.wait_closed()


class WebSocketProtocol(abc.ABC):
    """Base class for WebSocket protocol versions."""

    def __init__(self, handler, reader, writer) -> None:
        self.handler = handler
        self.client_terminated = False
        self.server_terminated = False

        self._reader: asyncio.StreamReader = reader
        self._writer: asyncio.StreamWriter = writer

    async def on_connection_close(self) -> None:
        await self._abort()

    async def _abort(self) -> None:
        """Instantly aborts the WebSocket connection by closing the socket"""
        self.client_terminated = True
        self.server_terminated = True

        self._writer.close()
        await self._writer.wait_closed()

        await self.close()  # let the subclass cleanup


class WebSocketProtocol13(CompressionMixin, WebSocketProtocol):
    """The class"""

    # Bit masks for the first byte of a frame.
    FIN = 0x80
    RSV1 = 0x40
    RSV2 = 0x20
    RSV3 = 0x10
    RSV_MASK = RSV1 | RSV2 | RSV3
    OPCODE_MASK = 0x0F

    stream = None

    settings = {
        'max_message_size': 10 * 1024 * 1024,
    }

    def __init__(self, handler, mask_outgoing, params, reader, writer):
        super().__init__(handler, reader, writer)
        self.params = params
        self.handler = handler

        self.client_terminated = False
        self.server_terminated = False
        self.mask_outgoing = mask_outgoing

        self._reader: asyncio.StreamReader = reader
        self._writer: asyncio.StreamWriter = writer

        self._final_frame = False
        self._frame_opcode = None
        self._masked_frame = None
        self._frame_mask = None
        self._frame_length = None
        self._fragmented_message_buffer = None
        self._fragmented_message_opcode = None
        self._waiting = None
        self._compression_options = params.compression_options
        self._decompressor = None
        self._compressor = None
        self._frame_compressed = None
        # The total uncompressed size of all messages received or sent.
        # Unicode messages are encoded to utf8.
        # Only for testing; subject to change.
        self._message_bytes_in = 0
        self._message_bytes_out = 0
        # The total size of all packets received or sent.  Includes
        # the effect of compression, frame overhead, and control frames.
        self._wire_bytes_in = 0
        self._wire_bytes_out = 0
        self._received_pong = False
        self.close_code = None
        self.close_reason = None
        self._ping_coroutine = None

    # Use a property for this to satisfy the abc.
    @property
    def selected_subprotocol(self) -> str:
        return self._selected_subprotocol

    @selected_subprotocol.setter
    def selected_subprotocol(self, value: str) -> None:
        self._selected_subprotocol = value

    async def accept_connection(self, headers, handler):
        """Performs WebSocket handshake."""
        try:
            self._handle_websocket_headers(headers)
        except ValueError:
            return await _send_http_error(
                self._writer,
                400,
                'Missing/Invalid WebSocket headers'
            )

        try:
            await self._accept_connection(handler)
        except asyncio.CancelledError:
            await self._abort()
        except ValueError:
            LOGGER.error("Malformed WebSocket request received", exc_info=True)
            await self._abort()

    @staticmethod
    def _handle_websocket_headers(headers) -> None:
        """Verifies all invariant- and required headers."""
        fields = ("Host", "Sec-WebSocket-Key", "Sec-WebSocket-Version")
        if not all(map(lambda f: headers.get(f), fields)):
            raise ValueError("Missing/Invalid WebSocket headers")

    @staticmethod
    def compute_accept_value(key) -> str:
        """Computes the value for the Sec-WebSocket-Accept header,
        given the value for Sec-WebSocket-Key.
        """
        return base64.b64encode(
            hashlib.sha1((key + _GUID).encode()).digest(),
        ).decode('utf-8')

    @staticmethod
    def _challenge_response(handler) -> str:
        return WebSocketProtocol13.compute_accept_value(
            handler.headers.get("Sec-WebSocket-Key")
        )

    async def _accept_connection(self, handler) -> None:
        protocol = ''
        extension = ''
        subprotocol_header = handler.headers.get("Sec-WebSocket-Protocol")
        if subprotocol_header:
            subprotocols = [s.strip() for s in subprotocol_header.split(",")]
        else:
            subprotocols = []

        self.selected_subprotocol = handler.select_subprotocol(subprotocols)
        if self.selected_subprotocol:
            assert self.selected_subprotocol in subprotocols
            protocol = f'Sec-WebSocket-Protocol: {self.selected_subprotocol})\r\n'

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
                extension = f'Sec-WebSocket-Extensions: {httputil._encode_header("permessage-deflate", ext[1])}\r\n'
                break

        response = (  # TODO: implement and rewrite with `set_header`
            'HTTP/1.1 101 Switching Protocols\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            f'Sec-WebSocket-Accept: {self._challenge_response(handler)}\r\n'
            f'{protocol}'
            f'{extension}'
            '\r\n'
        )
        self._writer.write(response.encode('utf-8'))
        await self._writer.drain()

        self.start_pinging()
        try:
            await handler.open()
        except Exception as exc:
            LOGGER.error(exc)
            await self._abort()
        else:
            await self._receive_frame_loop()

    @staticmethod
    def _parse_extensions_header(
        headers,
    ) -> list[tuple[str, dict[str, str]]]:
        extensions = headers.get("Sec-WebSocket-Extensions", "")
        if extensions:
            return [httputil._parse_header(e.strip()) for e in extensions.split(",")]
        return []

    async def on_close(self) -> None:
        """Invoked when the WebSocket is closed."""
        pass

    async def _write_frame(self, fin: bool, opcode: int, data: bytes, flags: int = 0):
        data_len = len(data)
        if opcode & 0x8:
            # All control frames MUST have a payload length of 125
            # bytes or less and MUST NOT be fragmented.
            if not fin:
                raise ValueError("control frames may not be fragmented")
            if data_len > 125:
                raise ValueError("control frame payloads may not exceed 125 bytes")

        finbit = self.FIN if fin else 0
        frame = struct.pack("B", finbit | opcode | flags)

        mask_bit = 0x80 if self.mask_outgoing else 0
        if data_len < 126:
            frame += struct.pack("B", data_len | mask_bit)
        elif data_len <= 0xFFFF:
            frame += struct.pack("!BH", 126 | mask_bit, data_len)
        else:
            frame += struct.pack("!BQ", 127 | mask_bit, data_len)

        if self.mask_outgoing:
            mask = os.urandom(4)
            masked_data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            frame += mask + masked_data
        else:
            frame += data

        self._wire_bytes_out += len(frame)

        self._writer.write(frame)
        await self._writer.drain()

    async def write_message(
        self, message: str | bytes | dict[str, 'Any'], binary: bool = False
    ):
        """Sends the given message to the client of this Web Socket."""
        opcode = 0x2 if binary else 0x1
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
        except StreamClosedError:
            raise WebSocketClosedError()

    async def write_ping(self, data: bytes) -> None:
        """Send ping frame."""
        assert isinstance(data, bytes)
        await self._write_frame(True, 0x9, data)

    async def _receive_frame_loop(self) -> None:
        try:
            while not self.client_terminated:
                await self._receive_frame()
        except StreamClosedError:
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
            data = bytes(b ^ self._frame_mask[i % 4] for i, b in enumerate(data))

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

    async def _handle_message(self, opcode: int, data: bytes):
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
            except StreamClosedError:
                await self._abort()
            await self.handler.on_ping(data)

        elif opcode == 0xA:
            # Pong
            self._received_pong = True
            return await self.handler.on_pong(data)

        else:
            await self._abort()

        return None

    async def close(self, code: int | None = None, reason: str | None =None):
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
                except StreamClosedError:
                    await self._abort()
            self.server_terminated = True

        if self.client_terminated:
            if self._waiting is not None:
                self._waiting = None
            self._writer.close()
            await self._writer.wait_closed()
        if self._ping_coroutine:
            self._ping_coroutine.cancel()
            self._ping_coroutine = None

        if not self.server_terminated:
            if code is None and reason is not None:
                code = 1000  # "normal closure" status code
            if code is None:
                close_data = b""
            else:
                close_data = struct.pack(">H", code)

            if reason is not None:
                close_data += reason.encode("utf-8")

            close_frame = self._write_frame(b"", 0x8)
            self._writer.write(close_frame)
            await self._writer.drain()

        self.server_terminated = True
        self._writer.close()
        await self._writer.wait_closed()
        await self.on_close()

    def is_closing(self) -> bool:
        """Return ``True`` if this connection is closing.

        The connection is considered closing if either side has
        initiated its closing handshake or if the stream has been
        shut down uncleanly.
        """
        return self.client_terminated or self.server_terminated

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
                # Note: using de_dupe_gen_log to prevent this message from
                # being duplicated for each connection
                LOGGER.warning(
                    f"The websocket_ping_timeout ({timeout}) cannot be longer"
                    f" than the websocket_ping_interval ({self.ping_interval})."
                    f"\nSetting websocket_ping_timeout={self.ping_interval}"
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
