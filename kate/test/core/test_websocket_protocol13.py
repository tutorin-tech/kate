"""The module contains the unit tests for the WebSocket protocol."""

import asyncio
import base64
import hashlib
import os
import socket
import struct
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from kate.core.websocket import (
    WebSocketClosedError,
    WebSocketHandler,
    WebSocketProtocol,
    WebSocketProtocol13,
    _WebSocketParams,
    _DecompressTooLargeError,
)


class _DummyServer:
    """Minimal server stub exposing send_http_error and optional .socket."""
    def __init__(self, with_socket: bool = False):
        self.send_http_error = AsyncMock()
        self.socket = None
        if with_socket:
            sock = Mock()
            sock.family = socket.AF_INET
            sock.setsockopt = Mock()
            self.socket = sock


def _make_rw():
    """Create reader/writer doubles suitable for unit testing."""
    reader = AsyncMock()
    writer = Mock()
    writer.write = Mock()
    writer.drain = AsyncMock()
    writer.close = Mock()
    writer.wait_closed = AsyncMock()
    writer.is_closing = Mock(return_value=False)
    return reader, writer


def _default_headers():
    return {
        "Host": "example.com",
        "Origin": "http://example.com",
        "Upgrade": "websocket",
        "Connection": "Upgrade",
        "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
    }


def _params(**kw):
    return _WebSocketParams(
        ping_interval=kw.get("ping_interval"),
        ping_timeout=kw.get("ping_timeout"),
        max_message_size=kw.get("max_message_size", 10 * 1024 * 1024),
        compression_options=kw.get("compression_options"),
    )


class _DummyProtocol(WebSocketProtocol):
    """Concrete minimal subclass to test WebSocketProtocol base behavior."""
    def __init__(self, handler, reader, writer):
        super().__init__(handler, reader, writer)
        self.close_called = False

    async def close(self, code=None, reason=None):
        self.close_called = True

    def is_closing(self) -> bool:
        return self.client_terminated or self.server_terminated

    async def accept_connection(self, handler: WebSocketHandler) -> None:
        return None

    async def write_message(self, message, binary=False) -> None:
        return None

    @property
    def selected_subprotocol(self):
        return None

    async def write_ping(self, data: bytes) -> None:
        return None

    def start_pinging(self) -> None:
        return None

    async def _receive_frame_loop(self) -> None:
        return None

    def set_nodelay(self, value: bool) -> None:
        return None


class TestWebSocketProtocolBase(unittest.IsolatedAsyncioTestCase):
    """The class implements the tests for the WebSocketProtocol base class."""

    async def test_abort_closes_writer_and_marks_terminated_and_calls_close(self):
        """The protocol should have the possibility to abort the connection, close the writer,
        set flags, and call close().
        """
        reader, writer = _make_rw()
        handler = Mock()
        protocol = _DummyProtocol(handler, reader, writer)

        await protocol._abort()

        self.assertTrue(protocol.client_terminated)
        self.assertTrue(protocol.server_terminated)
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()
        self.assertTrue(protocol.close_called)

    async def test_on_connection_close_delegates_to_abort(self):
        """The protocol should have the possibility to delegate on_connection_close
        to the abort routine.
        """
        reader, writer = _make_rw()
        handler = Mock()
        protocol = _DummyProtocol(handler, reader, writer)

        with patch.object(protocol, "_abort", AsyncMock()) as ab:
            await protocol.on_connection_close()
            ab.assert_awaited_once()



class TestWebSocketProtocol13Handshake(unittest.IsolatedAsyncioTestCase):
    """The class implements the tests for WebSocketProtocol13 handshake and negotiation."""

    def setUp(self):
        self.reader, self.writer = _make_rw()
        self.server = _DummyServer()
        self.headers = _default_headers()
        self.handler = WebSocketHandler(self.headers, self.reader, self.writer, self.server)

    async def test_accept_connection_sends_101_with_required_headers(self):
        """The protocol should have the possibility to send 101 Switching Protocols
        with required headers.
        """
        protocol = WebSocketProtocol13(self.handler, False, _params(), self.reader, self.writer)

        with patch.object(protocol, "_receive_frame_loop", AsyncMock()), \
             patch.object(self.handler, "open", AsyncMock()), \
             patch.object(protocol, "start_pinging", Mock()) as sp:
            await protocol.accept_connection(self.handler)
            sp.assert_called_once()

        payload = b"".join(call.args[0] for call in self.writer.write.call_args_list)
        self.assertIn(b"HTTP/1.1 101 Switching Protocols", payload)
        self.assertIn(b"Upgrade: websocket", payload)
        self.assertIn(b"Connection: Upgrade", payload)

        sha1 = hashlib.sha1()
        sha1.update(self.headers["Sec-WebSocket-Key"].encode())
        sha1.update(b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
        accept = base64.b64encode(sha1.digest())
        self.assertIn(b"Sec-WebSocket-Accept: " + accept, payload)

    async def test_accept_connection_sets_subprotocol_when_selected(self):
        """The protocol should have the possibility to set the Sec-WebSocket-Protocol
        header when a subprotocol is selected.
        """
        hdrs = dict(self.headers, **{"Sec-WebSocket-Protocol": "bad, goodproto"})
        handler = WebSocketHandler(hdrs, self.reader, self.writer, self.server)
        handler.select_subprotocol = Mock(return_value="goodproto")

        protocol = WebSocketProtocol13(handler, False, _params(), self.reader, self.writer)
        with patch.object(protocol, "_receive_frame_loop", AsyncMock()), \
             patch.object(handler, "open", AsyncMock()):
            await protocol.accept_connection(handler)

        payload = b"".join(call.args[0] for call in self.writer.write.call_args_list)
        self.assertIn(b"Sec-WebSocket-Protocol: goodproto", payload)

    async def test_accept_connection_negotiates_permessage_deflate(self):
        """The protocol should have the possibility to negotiate the permessage-deflate
        extension and set response header."""
        offered = "permessage-deflate; client_max_window_bits; server_max_window_bits=12"
        hdrs = dict(self.headers, **{"Sec-WebSocket-Extensions": offered})
        handler = WebSocketHandler(hdrs, self.reader, self.writer, self.server)

        protocol = WebSocketProtocol13(handler, False, _params(compression_options={}), self.reader, self.writer)

        with patch.object(protocol, "_create_compressors", Mock()), \
             patch.object(protocol, "_receive_frame_loop", AsyncMock()), \
             patch.object(handler, "open", AsyncMock()):
            await protocol.accept_connection(handler)

        payload = b"".join(call.args[0] for call in self.writer.write.call_args_list)
        # client_max_window_bits without a value must not be echoed back
        self.assertIn(b"Sec-WebSocket-Extensions: permessage-deflate; server_max_window_bits=12", payload)

    async def test_accept_connection_sends_400_when_headers_invalid(self):
        """The protocol should have the possibility to send 400 when the request
        is missing mandatory headers.
        """
        bad_handler = WebSocketHandler({"Host": "example.com"}, self.reader, self.writer, self.server)
        protocol = WebSocketProtocol13(bad_handler, False, _params(), self.reader, self.writer)

        await protocol.accept_connection(bad_handler)
        self.server.send_http_error.assert_awaited_once()
        self.assertEqual(self.server.send_http_error.await_args.args[1], 400)

    async def test_accept_connection_aborts_when_open_raises(self):
        """The protocol should have the possibility to abort the connection when
        handler.open raises an exception.
        """
        protocol = WebSocketProtocol13(self.handler, False, _params(), self.reader, self.writer)

        with patch.object(protocol, "_receive_frame_loop", AsyncMock()), \
             patch.object(protocol, "_abort", AsyncMock()) as mock_abort, \
             patch.object(self.handler, "open", AsyncMock(side_effect=RuntimeError("boom"))):
            await protocol.accept_connection(self.handler)
            mock_abort.assert_awaited_once()

    def test_compute_accept_value_matches_rfc(self):
        """The protocol should have the possibility to compute the correct
        Sec-WebSocket-Accept value.
        """
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode("utf-8")
        self.assertEqual(WebSocketProtocol13.compute_accept_value(key), expected)

    async def test_accept_connection_aborts_when_cancelled_error_or_value_error(self):
        """The protocol should have the possibility to abort when _accept_connection raises CancelledError or ValueError."""

        reader, writer = _make_rw()
        server = _DummyServer()

        handler = WebSocketHandler(self.headers, reader, writer, server)
        protocol = WebSocketProtocol13(handler, False, _params(), self.reader, self.writer)

        with patch.object(protocol, "_accept_connection",
                          AsyncMock(side_effect=asyncio.CancelledError)), \
            patch.object(protocol, "_abort", AsyncMock()) as ab:
            await protocol.accept_connection(handler)
            ab.assert_awaited_once()

        with patch.object(protocol, "_accept_connection", AsyncMock(side_effect=ValueError("bad"))), \
            patch.object(protocol, "_abort", AsyncMock()) as ab2:
            await protocol.accept_connection(self.handler)
            ab2.assert_awaited_once()


class TestWebSocketProtocol13Writing(unittest.IsolatedAsyncioTestCase):
    """The class implements the tests for writing frames and messages."""

    def setUp(self):
        self.reader, self.writer = _make_rw()
        self.server = _DummyServer()
        self.headers = _default_headers()
        self.handler = WebSocketHandler(self.headers, self.reader, self.writer, self.server)
        self.protocol = WebSocketProtocol13(
            self.handler,
            False,
            _params(),
            self.reader,
            self.writer
        )

    @patch.object(WebSocketProtocol13, "_write_frame", new_callable=AsyncMock)
    async def test_write_message_invokes_frame_writer_for_text(self, mock_write_frame):
        """The protocol should have the possibility to write a text message
        using the frame writer.
        """
        await self.protocol.write_message("hello")
        self.assertTrue(mock_write_frame.await_count >= 1)

    @patch.object(WebSocketProtocol13, "_write_frame", new_callable=AsyncMock, side_effect=ConnectionResetError)
    async def test_write_message_translates_connection_reset_to_closed_error(self, _wf):
        """The protocol should have the possibility to translate ConnectionResetError
        into WebSocketClosedError.
        """
        with self.assertRaises(WebSocketClosedError):
            await self.protocol.write_message("hello")

    @patch.object(WebSocketProtocol13, "_write_frame", new_callable=AsyncMock)
    async def test_write_ping_sends_control_frame(self, mock_write_frame):
        """The protocol should have the possibility to send a ping control frame."""
        await self.protocol.write_ping(b"data")
        mock_write_frame.assert_awaited_once_with(True, 0x9, b"data")

    async def test__write_frame_builds_lengths_and_mask_flag(self):
        """The frame writer should have the possibility to encode short/extended lengths and
        respect the mask flag.
        """
        await self.protocol._write_frame(True, 0x1, b"abc")
        frame = self.writer.write.call_args_list[-1].args[0]
        self.assertEqual(frame[0] & 0x0F, 0x1)
        self.assertEqual(frame[1] & 0x80, 0)   # no mask
        self.assertEqual(frame[1] & 0x7F, 3)

        # unmasked, extended 16
        self.writer.write.reset_mock()
        await self.protocol._write_frame(True, 0x2, b"a" * 200)
        frame = self.writer.write.call_args_list[-1].args[0]
        self.assertEqual(frame[1] & 0x7F, 126)

        # masked, extended 64
        proto2 = WebSocketProtocol13(self.handler, True, _params(), self.reader, self.writer)
        self.writer.write.reset_mock()
        big = b"a" * (1 << 16)
        await proto2._write_frame(True, 0x2, big)
        frame = self.writer.write.call_args_list[-1].args[0]
        self.assertEqual(frame[1] & 0x80, 0x80)  # masked
        self.assertEqual(frame[1] & 0x7F, 127)   # 64-bit length
        # frame = header2 + 8len + 4mask + payload
        # sanity-check total size includes 4 mask bytes
        self.assertGreater(len(frame), 2 + 8 + 4)

    async def test__write_frame_rejects_fragmented_control_and_large_control_payload(self):
        """The frame writer should have the possibility to reject fragmented control frames and control payloads > 125 bytes."""
        with self.assertRaises(ValueError):
            await self.protocol._write_frame(False, 0x9, b"x")
        with self.assertRaises(ValueError):
            await self.protocol._write_frame(True, 0x9, b"a" * 126)


class TestWebSocketProtocol13Reading(unittest.IsolatedAsyncioTestCase):
    """The class implements the tests for reading frames and handling messages."""

    def setUp(self):
        self.reader, self.writer = _make_rw()
        self.server = _DummyServer()
        self.headers = _default_headers()
        self.handler = WebSocketHandler(self.headers, self.reader, self.writer, self.server)
        self.protocol = WebSocketProtocol13(self.handler, False, _params(), self.reader, self.writer)

    def _mask(self, key: bytes, data: bytes) -> bytes:
        return bytes(b ^ key[i % 4] for i, b in enumerate(data))

    async def _feed_frame(self, fin, opcode, payload: bytes, *, masked=True, rsv1=False):
        """Feed a single frame through _read_bytes() path."""
        header = (0x80 if fin else 0x00) | (0x40 if rsv1 else 0x00) | opcode
        if masked:
            maskbit = 0x80
        else:
            maskbit = 0x00

        extend = b""
        l = len(payload)
        if l < 126:
            second = maskbit | l
        elif l <= 0xFFFF:
            second = maskbit | 126
            extend = struct.pack("!H", l)
        else:
            second = maskbit | 127
            extend = struct.pack("!Q", l)

        chunks = [struct.pack("BB", header, second), extend]
        if masked:
            key = os.urandom(4)
            chunks.append(key)
            payload = self._mask(key, payload)
        chunks.append(payload)

        side_effect = [c for c in chunks if c]
        self.protocol._read_bytes = AsyncMock(side_effect=side_effect)

        await self.protocol._receive_frame()

    async def test_text_message_is_decoded_and_passed_to_handler(self):
        """The protocol should have the possibility to decode a text frame and
        pass it to on_message.
        """
        self.handler.on_message = AsyncMock()
        await self._feed_frame(True, 0x1, b"hi", masked=True)
        self.handler.on_message.assert_awaited_once_with("hi")

    async def test_binary_message_is_forwarded_as_bytes(self):
        """The protocol should have the possibility to forward a binary frame to on_message."""
        self.handler.on_message = AsyncMock()
        await self._feed_frame(True, 0x2, b"\x00\x01", masked=False)
        self.handler.on_message.assert_awaited_once_with(b"\x00\x01")

    async def test_invalid_utf8_aborts_connection(self):
        """The protocol should have the possibility to abort the connection on invalid UTF-8."""
        with patch.object(self.protocol, "_abort", AsyncMock()) as ab:
            await self._feed_frame(True, 0x1, b"\xff\xff", masked=False)
            ab.assert_awaited()

    async def test_ping_echoes_pong_and_calls_handler(self):
        """The protocol should have the possibility to respond to ping with pong and
        notify the handler.
        """
        self.handler.on_ping = AsyncMock()
        with patch.object(self.protocol, "_write_frame", AsyncMock()) as wf:
            await self._feed_frame(True, 0x9, b"xyz", masked=False)
            wf.assert_awaited_once()
            self.handler.on_ping.assert_awaited_once_with(b"xyz")

    async def test_pong_sets_received_flag_and_calls_handler(self):
        """The protocol should have the possibility to set the received pong flag and
        call handler.on_pong.
        """
        self.handler.on_pong = AsyncMock()
        await self._feed_frame(True, 0xA, b"pong", masked=False)
        self.assertTrue(self.protocol._received_pong)
        self.handler.on_pong.assert_awaited_once_with(b"pong")

    async def test_close_frame_marks_client_terminated_and_echoes_code(self):
        """The protocol should have the possibility to mark client termination and
        echo the received close code.
        """
        with patch.object(self.protocol, "_write_frame", AsyncMock()) as wf:
            code = 1001
            payload = struct.pack(">H", code) + b"bye"
            await self._feed_frame(True, 0x8, payload, masked=False)
            self.assertTrue(self.protocol.client_terminated)
            self.assertEqual(self.protocol.close_code, 1001)
            self.assertEqual(self.protocol.close_reason, "bye")
            self.assertTrue(wf.await_count >= 1)

    async def test_reserved_bits_cause_abort(self):
        """The protocol should have the possibility to abort the connection when undefined
        reserved bits are set.
        """
        with patch.object(self.protocol, "_abort", AsyncMock()), patch.object(self.handler, 'on_message'):
            # set RSV2 to force abort
            await self._feed_frame(True, 0x1, b"x", masked=False, rsv1=False)
            # rsv1 False here; to set rsv2 we'd need a custom craft; simulate by setting reserved_bits via patch:

        header = struct.pack("BB", WebSocketProtocol13.FIN | WebSocketProtocol13.RSV2 | 0x1, 0)
        self.protocol._read_bytes = AsyncMock(side_effect=[header])
        with patch.object(self.protocol, "_abort", AsyncMock()) as ab2:
            await self.protocol._receive_frame()
            ab2.assert_awaited()

    async def test_control_frame_fragmentation_or_length_violation_aborts(self):
        """The protocol should have the possibility to abort on fragmented control frames or
        payload length >= 126.
        """
        header = struct.pack("BB", 0x09, 0x01)  # FIN=0, opcode=ping, len=1
        self.protocol._read_bytes = AsyncMock(side_effect=[header, b"\x00"])
        with patch.object(self.protocol, "_abort", AsyncMock()) as ab:
            await self.protocol._receive_frame()
            ab.assert_awaited()

        # overlong ping len=126 -> header second byte 0xFE (mask=1 would be 0xFE; we use unmasked 126)
        header = struct.pack("BB", 0x89, 126)
        self.protocol._read_bytes = AsyncMock(side_effect=[header, b"\x00\x7e", b"a" * 126])
        with patch.object(self.protocol, "_abort", AsyncMock()) as ab2:
            await self.protocol._receive_frame()
            ab2.assert_awaited()

    async def test_fragmentation_rules_are_enforced(self):
        """The protocol should have the possibility to enforce fragmentation rules
        (continuation and new data).
        """
        header = struct.pack("BB", 0x80 | 0x00, 0x00)  # FIN, opcode=0, len=0
        self.protocol._read_bytes = AsyncMock(side_effect=[header, header])
        with patch.object(self.protocol, "_abort", AsyncMock()) as ab:
            await self.protocol._receive_frame()
            ab.assert_awaited()

        first = struct.pack("BB", 0x01, 0x01) + b"a"
        second = struct.pack("BB", 0x02, 0x01) + b"b"
        self.protocol._read_bytes = AsyncMock(
            side_effect=[first[:2], first[2:], second[:2], second[2:]]
        )
        with patch.object(self.protocol, "_abort", AsyncMock()) as ab2:
            await self.protocol._receive_frame()
            await self.protocol._receive_frame()
            ab2.assert_awaited()

    async def test_max_message_size_violation_closes_and_aborts(self):
        """The protocol should have the possibility to close with 1009 and abort when
        the message exceeds the size limit.
        """
        small_params = _params(max_message_size=3)
        self.protocol = WebSocketProtocol13(
            self.handler,
            False,
            small_params,
            self.reader,
            self.writer
        )

        # build header indicating length 4 (<126)
        header = struct.pack("BB", 0x81, 0x04)
        self.protocol._read_bytes = AsyncMock(side_effect=[header, b"DATA"])
        with patch.object(self.protocol, "close", AsyncMock()) as close_mock, \
             patch.object(self.protocol, "_abort", AsyncMock()) as ab:
            await self.protocol._receive_frame()
            close_mock.assert_awaited()
            ab.assert_awaited()

    async def test_compressed_text_message_is_decompressed_then_dispatched(self):
        """The protocol should have the possibility to decompress a compressed message when RSV1 is set and a decompressor is present."""
        class FakeDecomp:
            def decompress(self, data: bytes) -> bytes:
                return b"hello"

        self.protocol._decompressor = FakeDecomp()
        self.handler.on_message = AsyncMock()

        # RSV1 set, opcode=0x1, FIN=1, len=1, payload=b"x" (will decompress to b"hello")
        header = struct.pack("BB", 0x80 | 0x40 | 0x1, 0x01)
        self.protocol._read_bytes = AsyncMock(side_effect=[header, b"x"])
        await self.protocol._receive_frame()
        self.handler.on_message.assert_awaited_once_with("hello")

    async def test_decompress_too_large_is_handled(self):
        """The protocol should have the possibility to close with 1009 and abort when decompression exceeds max size."""
        class Boom:
            def decompress(self, data: bytes) -> bytes:
                raise _DecompressTooLargeError()

        self.protocol._decompressor = Boom()
        with patch.object(self.protocol, "close", AsyncMock()) as close_mock, \
             patch.object(self.protocol, "_abort", AsyncMock()) as ab:
            header = struct.pack("BB", 0x80 | 0x40 | 0x1, 0x00)  # RSV1 text, empty
            self.protocol._read_bytes = AsyncMock(side_effect=[header, header])
            await self.protocol._receive_frame()
            close_mock.assert_awaited()
            ab.assert_awaited()

    async def test_receive_frame_loop_handles_connection_reset_and_notifies_handler(self):
        """The protocol should have the possibility to abort on ConnectionResetError and
        notify the handler of closure.
        """
        with patch.object(self.protocol, "_receive_frame", AsyncMock(side_effect=ConnectionResetError)), \
             patch.object(self.protocol, "_abort", AsyncMock()) as ab, \
             patch.object(self.handler, "on_ws_connection_close", AsyncMock()) as onclose:
            await self.protocol._receive_frame_loop()
            ab.assert_awaited()
            onclose.assert_awaited()

    async def test_read_bytes_reads_exactly_n_and_updates_wire_counter(self):
        """The method should have the possibility to read exactly N bytes and update the wire-in counter."""
        reader = AsyncMock()
        writer = Mock()
        writer.is_closing = Mock(return_value=False)

        reader.readexactly = AsyncMock(side_effect=[b"abc", b"de"])

        server = _DummyServer()
        handler = WebSocketHandler(_default_headers(), reader, writer, server)
        params = _WebSocketParams(ping_interval=None, ping_timeout=None, max_message_size=1024,
                                  compression_options=None)
        proto = WebSocketProtocol13(handler, False, params, reader, writer)

        self.assertEqual(proto._wire_bytes_in, 0)

        data1 = await proto._read_bytes(3)
        self.assertEqual(data1, b"abc")
        self.assertEqual(proto._wire_bytes_in, 3)

        data2 = await proto._read_bytes(2)
        self.assertEqual(data2, b"de")
        self.assertEqual(proto._wire_bytes_in, 5)

        reader.readexactly.assert_has_awaits([unittest.mock.call(3), unittest.mock.call(2)])


class TestWebSocketProtocol13TimersAndSocket(unittest.TestCase):
    """The class implements the tests for timers, ping helpers, and socket options."""

    def setUp(self):
        self.reader, self.writer = _make_rw()
        self.server = _DummyServer(with_socket=True)
        self.headers = _default_headers()
        self.handler = WebSocketHandler(self.headers, self.reader, self.writer, self.server)
        self.protocol = WebSocketProtocol13(
            self.handler,
            False,
            _params(),
            self.reader,
            self.writer
        )

    def test_is_closing_reports_true_when_any_side_terminated(self):
        """The protocol should have the possibility to report a closing state when
        either side is terminated.
        """
        self.assertFalse(self.protocol.is_closing())
        self.protocol.client_terminated = True
        self.assertTrue(self.protocol.is_closing())
        self.protocol.client_terminated = False
        self.protocol.server_terminated = True
        self.assertTrue(self.protocol.is_closing())

    def test_set_nodelay_sets_tcp_nodelay_on_inet_sockets(self):
        """The protocol should have the possibility to toggle TCP_NODELAY on the server
        socket when applicable.
        """
        self.protocol.set_nodelay(True)
        self.server.socket.setsockopt.assert_called_once_with(
            socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
        )
        self.server.socket.setsockopt.reset_mock()
        self.protocol.set_nodelay(False)
        self.server.socket.setsockopt.assert_called_once_with(
            socket.IPPROTO_TCP, socket.TCP_NODELAY, 0
        )

    def test_ping_interval_and_timeout_values_and_auto_clamp(self):
        """The protocol should have the possibility to expose ping interval/timeout and clamp timeout when longer than interval."""
        p = WebSocketProtocol13(
            self.handler,
            False,
            _params(ping_interval=5.0, ping_timeout=10.0),
            self.reader,
            self.writer,
        )
        # timeout > interval: clamped to interval
        self.assertEqual(p.ping_interval, 5.0)
        self.assertEqual(p.ping_timeout, 5.0)

        p2 = WebSocketProtocol13(
            self.handler,
            False,
            _params(ping_interval=0.0, ping_timeout=None),
            self.reader,
            self.writer,
        )
        self.assertEqual(p2.ping_interval, 0.0)
        self.assertEqual(p2.ping_timeout, p2.ping_interval)

    @patch("asyncio.create_task")
    def test_start_pinging_starts_background_task_only_once(self, create_task):
        """The protocol should have the possibility to start a single periodic ping coroutine when interval is positive."""
        p = WebSocketProtocol13(
            self.handler,
            False,
            _params(ping_interval=1.0, ping_timeout=0.0),
            self.reader,
            self.writer
        )
        self.assertIsNone(p._ping_coroutine)
        p.start_pinging()
        create_task.assert_called_once()

        create_task.reset_mock()
        p.start_pinging()
        create_task.assert_not_called()

    def test_ping_sleep_time_computes_next_delay(self):
        """The protocol should have the possibility to compute the sleep time until the next ping."""
        self.assertEqual(
            WebSocketProtocol13.ping_sleep_time(last_ping_time=100.0, interval=10.0, now=104.0),
            6.0,
        )


class TestWebSocketProtocol13PeriodicPing(unittest.IsolatedAsyncioTestCase):
    """The class implements the tests for the periodic ping coroutine."""

    def setUp(self):
        self.reader, self.writer = _make_rw()
        self.server = _DummyServer()
        self.headers = _default_headers()
        self.handler = WebSocketHandler(self.headers, self.reader, self.writer, self.server)

    @patch("asyncio.sleep", new_callable=AsyncMock, side_effect=[None])
    async def test_periodic_ping_closes_on_missing_pong_when_timeout_positive(self, _sleep):
        """The protocol should have the possibility to close the connection if a pong is not received within the timeout."""
        protocol = WebSocketProtocol13(
            self.handler, False, _params(ping_interval=0.01, ping_timeout=0.02), self.reader, self.writer
        )
        protocol.write_ping = AsyncMock()
        protocol.close = AsyncMock()
        with patch.object(time, "time", return_value=1000.0), patch('asyncio.sleep'):
            await protocol.periodic_ping()

        protocol.write_ping.assert_awaited()
        protocol.close.assert_awaited_once_with(reason="ping timed out")


class TestWebSocketProtocol13CompressionHelpers(unittest.TestCase):
    """The class implements the tests for compression helpers of WebSocketProtocol13."""

    def setUp(self):
        _, writer = _make_rw()
        self.reader = AsyncMock()
        self.writer = writer
        self.server = _DummyServer()

        self.headers = {
            "Host": "example.com",
            "Origin": "http://example.com",
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
        }
        self.handler = WebSocketHandler(self.headers, self.reader, self.writer, self.server)

        self.params = _WebSocketParams(
            ping_interval=None,
            ping_timeout=None,
            max_message_size=10 * 1024 * 1024,
            compression_options=None,
        )
        self.protocol = WebSocketProtocol13(
            self.handler, False, self.params, self.reader, self.writer
        )

    def test_get_compressor_options_server_role_persistence_and_max_wbits(self):
        """The helper should have the possibility to compute server options
        (persistence and max_wbits) from server_* keys.
        """
        opts = self.protocol._get_compressor_options(
            "server",
            agreed_parameters={"server_max_window_bits": "10"},
            compression_options={"level": 3},
        )
        self.assertEqual(opts["max_wbits"], 10)
        self.assertTrue(opts["persistent"])
        self.assertEqual(opts["compression_options"], {"level": 3})

        opts2 = self.protocol._get_compressor_options(
            "server",
            agreed_parameters={"server_no_context_takeover": None, "server_max_window_bits": "15"},
            compression_options=None,
        )
        self.assertEqual(opts2["max_wbits"], 15)
        self.assertFalse(opts2["persistent"])

    def test_get_compressor_options_client_role_uses_client_keys(self):
        """The helper should have the possibility to compute client options from client_* keys."""
        opts = self.protocol._get_compressor_options(
            "client",
            agreed_parameters={"client_max_window_bits": "12"},
            compression_options={"mem_level": 8},
        )
        self.assertEqual(opts["max_wbits"], 12)
        self.assertTrue(opts["persistent"])

        opts2 = self.protocol._get_compressor_options(
            "client",
            agreed_parameters={"client_no_context_takeover": None, "client_max_window_bits": "11"},
            compression_options=None,
        )
        self.assertEqual(opts2["max_wbits"], 11)
        self.assertFalse(opts2["persistent"])

    def test_get_compressor_options_defaults_when_values_absent(self):
        """The helper should have the possibility to provide default values when bits and
        options are not present.
        """
        opts = self.protocol._get_compressor_options(
            "server",
            agreed_parameters={},
            compression_options=None,
        )
        self.assertIn("max_wbits", opts)
        self.assertIsInstance(opts["max_wbits"], int)
        self.assertIn("persistent", opts)

    def test_create_compressors_initializes_members_and_roundtrips_payload(self):
        """The helper should have the possibility to create compressor and decompressor that can roundtrip payloads."""
        ext_params = {"server_max_window_bits": "12"}  # minimal valid negotiation
        self.protocol._create_compressors(
            "server",
            agreed_parameters=ext_params,
            compression_options={"level": 1},
        )

        self.assertIsNotNone(self.protocol._compressor)
        self.assertIsNotNone(self.protocol._decompressor)

        payload = b"hello websocket" * 50
        compressed = self.protocol._compressor.compress(payload)
        restored = self.protocol._decompressor.decompress(compressed)
        self.assertEqual(restored, payload)

    def test_create_compressors_supports_client_role_keys(self):
        """The helper should have the possibility to read client_* keys when role is 'client'."""
        protocol = WebSocketProtocol13(self.handler, False, self.params, self.reader, self.writer)
        ext_params = {"client_max_window_bits": "11", "client_no_context_takeover": None}
        protocol._create_compressors("client", agreed_parameters=ext_params, compression_options=None)

        self.assertIsNotNone(protocol._compressor)
        self.assertIsNotNone(protocol._decompressor)

        data = b"x" * 1024
        self.assertEqual(protocol._decompressor.decompress(protocol._compressor.compress(data)), data)

    def test_create_compressors_raises_for_unsupported_parameter(self):
        """The helper should have the possibility to raise an error
        for unsupported extension parameters.
        """
        with self.assertRaises(ValueError):
            self.protocol._create_compressors("server", {"unknown_param": "1"}, {})

    def test_create_compressors_ignores_client_max_window_bits_without_value(self):
        """The helper should have the possibility to ignore a client_max_window_bits
        parameter without a value.
        """
        ext_params = {
            "server_max_window_bits": "10",
            "client_max_window_bits": None,
        }
        self.protocol._create_compressors("server", ext_params, {})
        self.assertIsNotNone(self.protocol._compressor)
        self.assertIsNotNone(self.protocol._decompressor)

