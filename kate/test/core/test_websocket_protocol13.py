"""The module contains the unit tests for the WebSocket protocol."""

# ruff: noqa: FBT003, SLF001

import asyncio
import base64
import enum
import hashlib
import socket
import struct
import unittest
import zlib
from itertools import count
from unittest.mock import AsyncMock, Mock, patch

from kate.core.escape import json_encode, utf8
from kate.core.util import _websocket_mask_python
from kate.core.websocket import (
    GZIP_LEVEL,
    WebSocketClosedError,
    WebSocketHandler,
    WebSocketProtocol,
    WebSocketProtocol13,
    _DecompressTooLargeError,
)
from kate.core.websocket import _PerMessageDeflateCompressor as Compressor
from kate.core.websocket import _PerMessageDeflateDecompressor as Decompressor
from kate.test.core.base import BaseWebSocketTestCase, DummyServer, get_params

_MAGIC_WEBSOCKET_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


class BitMask:
    """The class implements the enum for the bit masks used to extract specific fields
    from WebSocket frame headers.
    """

    # Bit masks for the first byte of a frame.
    FINAL = 0x80
    RSV1 = 0x40
    RSV2 = 0x20
    RSV3 = 0x10
    RSV_MASK = RSV1 | RSV2 | RSV3
    OPCODE = 0x0F

    # Bit masks for the second byte of a frame.
    MASK = 0x80
    PAYLOAD_LEN = 0x7F


class FinalBit(enum.IntEnum):
    """The class implements the enum for the WebSocket protocol final bit."""

    FINAL = 0x80
    NOT_FINAL = 0


class MaskBit(enum.IntEnum):
    """The class implements the enum for the WebSocket protocol mask bits."""

    MASKED = 0x80
    UNMASKED = 0


class Opcode(enum.IntEnum):
    """The class implements the enum for the WebSocket protocol opcodes."""

    CONTINUATION = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA


class TestWebSocketProtocolBase(BaseWebSocketTestCase):
    """The class implements the tests for the WebSocketProtocol base class."""

    class _DummyProtocol(WebSocketProtocol):
        """The class represents a concrete minimal subclass to test WebSocketProtocol
        base behavior.
        """

        def __init__(self, handler, reader, writer):
            """Initialize a _DummyProtocol object."""
            super().__init__(handler, reader, writer)
            self.close_called = False

        async def close(self, _code=None, _reason=None):
            """Close the protocol."""
            self.close_called = True

        def is_closing(self):
            """Return True if the protocol is closing."""
            return self.client_terminated or self.server_terminated

        async def accept_connection(self, _handler):
            """Accept the connection."""

        async def write_message(self, _message, _binary=False):  # noqa: FBT002
            """Write a message."""

        @property
        def selected_subprotocol(self):
            """Return the selected subprotocol."""

        async def write_ping(self, _data):
            """Write a ping."""

        def _process_server_headers(self, _key, _headers):
            """Process the server headers."""

        def start_pinging(self):
            """Start pinging."""

        async def _receive_frame_loop(self):
            """Receive a frame loop."""

        def set_nodelay(self, _value):
            """Set the nodelay."""

    async def test_abort_sets_termination_flags_closes_writer_waits_and_calls_close(self):
        """The protocol should have the possibility to abort the connection, set the termination
        flags, close and await the writer, and call close().
        """
        self.protocol = self._DummyProtocol(self.handler, self.reader, self.writer)

        await self.protocol._abort()

        self.assertTrue(self.protocol.client_terminated)
        self.assertTrue(self.protocol.server_terminated)

        self.writer.close.assert_called_once()
        self.writer.wait_closed.assert_awaited_once()

        self.assertTrue(self.protocol.close_called)

    async def test_on_connection_close_invokes_abort(self):
        """The protocol should have the possibility to invoke the abort routine from
        on_connection_close.
        """
        self.protocol = self._DummyProtocol(self.handler, self.reader, self.writer)

        with patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort:
            await self.protocol.on_connection_close()

        mock_abort.assert_awaited_once()

    def test_process_server_headers_sets_selected_subprotocol(self):
        """The protocol should have the possibility to validate server headers and store
        the selected subprotocol.
        """
        key = 'dGhlIHNhbXBsZSBub25jZQ=='
        accept_value = WebSocketProtocol13.compute_accept_value(key)
        headers = {
            'Upgrade': 'websocket',
            'Connection': 'Upgrade',
            'Sec-Websocket-Accept': accept_value,
            'Sec-WebSocket-Protocol': 'chat',
        }

        self.protocol._process_server_headers(key, headers)

        self.assertEqual(self.protocol.selected_subprotocol, 'chat')

    def test_process_server_headers_initializes_client_compressors(self):
        """The protocol should have the possibility to initialize client-side compressors
        when permessage-deflate is negotiated.
        """
        key = 'dGhlIHNhbXBsZSBub25jZQ=='
        accept_value = WebSocketProtocol13.compute_accept_value(key)
        headers = {
            'Upgrade': 'websocket',
            'Connection': 'Upgrade',
            'Sec-Websocket-Accept': accept_value,
            'Sec-WebSocket-Extensions': 'permessage-deflate; client_max_window_bits=12',
        }
        protocol = WebSocketProtocol13(
            self.handler,
            False,
            get_params(compression_options={}),
            self.reader,
            self.writer,
        )

        with patch.object(protocol, '_create_compressors', Mock()) as mock_create_compressors:
            protocol._process_server_headers(key, headers)

        mock_create_compressors.assert_called_once_with(
            'client',
            {'client_max_window_bits': '12'},
        )

    def test_process_server_headers_raises_for_unsupported_extensions(self):
        """The protocol should have the possibility to raise ValueError for unsupported
        extensions offered by the server.
        """
        key = 'dGhlIHNhbXBsZSBub25jZQ=='
        accept_value = WebSocketProtocol13.compute_accept_value(key)
        headers = {
            'Upgrade': 'websocket',
            'Connection': 'Upgrade',
            'Sec-Websocket-Accept': accept_value,
            'Sec-WebSocket-Extensions': 'foo-extension',
        }
        protocol = WebSocketProtocol13(
            self.handler,
            False,
            get_params(compression_options={}),
            self.reader,
            self.writer,
        )

        with self.assertRaises(ValueError):
            protocol._process_server_headers(key, headers)

    def test_set_nodelay_sets_tcp_nodelay_on_inet_sockets(self):
        """The protocol should have the possibility to toggle TCP_NODELAY on the server
        socket when applicable.
        """
        server = DummyServer(with_socket=True)
        handler = WebSocketHandler(Mock(), self.reader, self.writer, server)
        protocol = WebSocketProtocol13(
            handler,
            False,
            get_params(),
            self.reader,
            self.writer,
        )
        params = (socket.IPPROTO_TCP, socket.TCP_NODELAY)

        protocol.set_nodelay(True)
        server.socket.setsockopt.assert_called_once_with(*params, 1)

        server.socket.setsockopt.reset_mock()

        protocol.set_nodelay(False)
        server.socket.setsockopt.assert_called_once_with(*params, 0)


class TestWebSocketProtocol13Handshake(BaseWebSocketTestCase):
    """The class implements the tests for WebSocketProtocol13 handshake and negotiation."""

    async def test_accept_connection_aborts_when_cancelled_error(self):
        """The protocol should have the possibility to abort when _accept_connection
        raises CancelledError.
        """
        with (
            patch.object(
                self.protocol, '_accept_connection', AsyncMock(side_effect=asyncio.CancelledError),
            ),
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
        ):
            await self.protocol.accept_connection(self.handler)

        mock_abort.assert_awaited_once()

    async def test_accept_connection_aborts_when_open_raises(self):
        """The protocol should have the possibility to abort the connection when
        handler.open raises an exception.
        """
        with (
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
            patch.object(self.handler, 'open', AsyncMock(side_effect=RuntimeError)),
        ):
            await self.protocol.accept_connection(self.handler)

        mock_abort.assert_awaited_once()

    async def test_accept_connection_aborts_when_value_error(self):
        """The protocol should have the possibility to abort when _accept_connection
        raises ValueError.
        """
        with (
            patch.object(self.protocol, '_accept_connection', AsyncMock(side_effect=ValueError)),
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
        ):
            await self.protocol.accept_connection(self.handler)

        mock_abort.assert_awaited_once()

    async def test_accept_connection_omits_client_max_window_bits_without_value(self):
        """The protocol should have the possibility to omit the client_max_window_bits parameter
        when the client offers it without a value.
        """
        protocol = WebSocketProtocol13(
            self.handler,
            False,
            get_params(compression_options={}),
            self.reader,
            self.writer,
        )
        with (
            patch.object(protocol, '_parse_extensions_header',
                side_effect=lambda _headers: [(
                    'permessage-deflate', {
                        'client_max_window_bits': None,
                        'server_max_window_bits': '12',
                    }),
                ],
            ),
            patch.object(protocol, '_create_compressors'),
            patch.object(self.handler, 'open'),
            patch.object(protocol, '_receive_frame_loop'),
        ):
            await protocol.accept_connection(self.handler)

        response = b''.join(call.args[0] for call in self.writer.write.call_args_list)
        self.assertIn(
            b'Sec-WebSocket-Extensions: '
            b'permessage-deflate; server_max_window_bits=12',
            response,
        )
        self.assertNotIn(b'client_max_window_bits', response)

    async def test_accept_connection_sends_101_with_required_headers(self):
        """The protocol should have the possibility to send 101 Switching Protocols
        with required headers.
        """
        with (
            patch.object(self.protocol, 'start_pinging', Mock()) as mock_start_pinging,
            patch.object(self.handler, 'open', AsyncMock()) as mock_open,
            patch.object(
                self.protocol, '_receive_frame_loop', AsyncMock(),
            ) as mock_receive_frame_loop,
        ):
            await self.protocol.accept_connection(self.handler)

        mock_start_pinging.assert_called_once()
        mock_open.assert_awaited_once_with()
        mock_receive_frame_loop.assert_awaited_once()

        response = b''.join(
            call.args[0]
            for call in self.writer.write.call_args_list
        )
        self.assertIn(b'HTTP/1.1 101 Switching Protocols', response)
        self.assertIn(b'Upgrade: websocket', response)
        self.assertIn(b'Connection: Upgrade', response)

        sha1 = hashlib.sha1()  # noqa: S324
        sha1.update(self.headers['Sec-WebSocket-Key'].encode())
        sha1.update(_MAGIC_WEBSOCKET_GUID.encode())
        accept = base64.b64encode(sha1.digest())
        self.assertIn(b'Sec-WebSocket-Accept: ' + accept, response)

    async def test_accept_connection_sends_400_when_headers_invalid(self):
        """The protocol should have the possibility to send 400 when the request
        is missing mandatory headers.
        """
        bad_handler = WebSocketHandler(
            {'Host': 'example.com'}, self.reader, self.writer, self.server,
        )
        protocol = WebSocketProtocol13(bad_handler, False, get_params(), self.reader, self.writer)

        await protocol.accept_connection(bad_handler)

        self.server.send_http_error.assert_awaited_once_with(
            self.writer,
            400,
            'Missing/Invalid WebSocket headers',
        )

    async def test_accept_connection_sets_subprotocol_when_selected(self):
        """The protocol should have the possibility to set the Sec-WebSocket-Protocol
        header when a subprotocol is selected.
        """
        headers = dict(self.headers, **{'Sec-WebSocket-Protocol': 'bad, good'})
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)
        handler.open_args = ()
        handler.open_kwargs = {}
        handler.select_subprotocol = Mock(return_value='good')

        protocol = WebSocketProtocol13(handler, False, get_params(), self.reader, self.writer)
        with (
            patch.object(protocol, '_receive_frame_loop'),
            patch.object(handler, 'open'),
        ):
            await protocol.accept_connection(handler)

        response = b''.join(call.args[0] for call in self.writer.write.call_args_list)
        self.assertIn(b'Sec-WebSocket-Protocol: good', response)

    def test_compute_accept_value_matches_rfc(self):
        """The protocol should have the possibility to compute the correct
        Sec-WebSocket-Accept value.
        """
        key = 'dGhlIHNhbXBsZSBub25jZQ=='
        expected = base64.b64encode(
            hashlib.sha1((key + _MAGIC_WEBSOCKET_GUID).encode()).digest(),  # noqa: S324
        ).decode('utf-8')

        self.assertEqual(WebSocketProtocol13.compute_accept_value(key), expected)


class TestWebSocketProtocol13Close(BaseWebSocketTestCase):
    """The class implements the tests for closing the protocol connection."""

    async def test_close_aborts_on_connection_reset_error(self):
        """The protocol should have the possibility to abort if writing the close frame
        raises ConnectionResetError.
        """
        with (
            patch.object(
                self.protocol, '_write_frame', AsyncMock(side_effect=ConnectionResetError),
            ),
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
        ):
            await self.protocol.close(1000)

        mock_abort.assert_awaited_once()
        self.assertTrue(self.protocol.server_terminated)

    async def test_close_cancels_ping_coroutine(self):
        """The protocol should have the possibility to cancel the ping coroutine on close."""
        ping_coroutine = Mock()
        ping_coroutine.cancel = Mock()
        self.protocol._ping_coroutine = ping_coroutine
        with patch.object(self.protocol, '_write_frame', AsyncMock()) as mock_write_frame:
            await self.protocol.close(1000)

        mock_write_frame.assert_awaited_once_with(True, Opcode.CLOSE, struct.pack('>H', 1000))
        ping_coroutine.cancel.assert_called_once()
        self.assertIsNone(self.protocol._ping_coroutine)

    async def test_close_closes_stream_when_client_already_terminated(self):
        """The protocol should have the possibility to close and await the stream when
        the client has already terminated the connection.
        """
        self.protocol.client_terminated = True
        with patch.object(self.protocol, '_write_frame', AsyncMock()) as mock_write_frame:
            await self.protocol.close()

        mock_write_frame.assert_awaited_once_with(True, Opcode.CLOSE, b'')
        self.writer.close.assert_called_once()
        self.writer.wait_closed.assert_awaited_once()

    async def test_close_defaults_code_to_1000_when_only_reason_provided(self):
        """The protocol should have the possibility to default the close code to 1000
        when only a reason is supplied.
        """
        reason = 'normal'
        with patch.object(self.protocol, '_write_frame', AsyncMock()) as mock_write_frame:
            await self.protocol.close(reason=reason)

        expected_payload = struct.pack('>H', 1000) + utf8(reason)
        mock_write_frame.assert_awaited_once_with(True, Opcode.CLOSE, expected_payload)
        self.assertTrue(self.protocol.server_terminated)

    async def test_close_sends_close_frame_with_code_and_reason(self):
        """The protocol should have the possibility to send a close control frame with
        the provided code and reason.
        """
        close_reason = 'going away'
        close_code = 1001
        with patch.object(self.protocol, '_write_frame', AsyncMock()) as mock_write_frame:
            await self.protocol.close(close_code, close_reason)

        expected_payload = struct.pack('>H', close_code) + utf8(close_reason)
        mock_write_frame.assert_awaited_once_with(True, Opcode.CLOSE, expected_payload)
        self.assertTrue(self.protocol.server_terminated)

    async def test_close_skips_writing_frame_when_stream_is_closing(self):
        """The protocol should have the possibility to skip sending a close frame when
        the underlying stream is already closing.
        """
        self.writer.is_closing.return_value = True
        with patch.object(self.protocol, '_write_frame', AsyncMock()) as mock_write_frame:
            await self.protocol.close(1000)

        mock_write_frame.assert_not_called()
        self.assertTrue(self.protocol.server_terminated)

    def test_is_closing_reports_true_when_any_side_terminated(self):  # may need movement
        """The protocol should have the possibility to report a closing state when
        either side is terminated.
        """
        self.assertFalse(self.protocol.is_closing())

        self.protocol.client_terminated = True
        self.assertTrue(self.protocol.is_closing())

        self.protocol.client_terminated = False
        self.protocol.server_terminated = True
        self.assertTrue(self.protocol.is_closing())


class TestWebSocketProtocol13Writing(BaseWebSocketTestCase):
    """The class implements the tests for writing frames and messages."""

    async def test_write_message_encodes_text_and_delegates_to_frame_writer(self):
        """The protocol should have the possibility to encode text messages to UTF-8
        and forward them to the frame writer.
        """
        message = 'hello'
        with patch.object(WebSocketProtocol13, '_write_frame', AsyncMock()) as mock_write_frame:
            await self.protocol.write_message(message)

        self.assertEqual(self.protocol._message_bytes_out, len(message))
        mock_write_frame.assert_awaited_once_with(True, Opcode.TEXT, utf8(message), flags=0)

    async def test_write_message_forwards_binary_payload_to_frame_writer(self):
        """The protocol should have the possibility to forward binary messages to
        the frame writer without re-encoding.
        """
        message = b'hello \xe9'  # invalid UTF-8 sequence
        with patch.object(WebSocketProtocol13, '_write_frame', AsyncMock()) as mock_write_frame:
            await self.protocol.write_message(message, binary=True)

        self.assertEqual(self.protocol._message_bytes_out, len(message))
        mock_write_frame.assert_awaited_once_with(True, Opcode.BINARY, utf8(message), flags=0)

    async def test_write_message_uses_compression_and_sets_rsv1_flag(self):
        """The protocol should have the possibility to compress text messages when
        the compressor is configured and set the RSV1 flag.
        """
        compressed_message = b'compressed'

        class _Compressor:
            @staticmethod
            def compress(_data):
                return compressed_message

        self.protocol._compressor = _Compressor()

        message = 'message'
        with patch.object(WebSocketProtocol13, '_write_frame', AsyncMock()) as mock_write_frame:
            await self.protocol.write_message(message)

        self.assertEqual(self.protocol._message_bytes_out, len(message))
        mock_write_frame.assert_awaited_once_with(
            True,
            Opcode.TEXT,
            compressed_message,
            flags=WebSocketProtocol13.RSV1,
        )

    async def test_write_message_serializes_dicts_before_forwarding(self):
        """The protocol should have the possibility to serialize dictionary messages
        to JSON before delegating to the frame writer.
        """
        message = {'key': 'value'}
        encoded_message = utf8(json_encode(message))
        with patch.object(WebSocketProtocol13, '_write_frame', AsyncMock()) as mock_write_frame:
            await self.protocol.write_message(message)

        self.assertEqual(self.protocol._message_bytes_out, len(encoded_message))
        mock_write_frame.assert_awaited_once_with(True, Opcode.TEXT, encoded_message, flags=0)

    async def test_write_message_translates_connection_reset_to_closed_error(self):
        """The protocol should have the possibility to translate ConnectionResetError
        into WebSocketClosedError.
        """
        with (
            patch.object(WebSocketProtocol13, '_write_frame', side_effect=ConnectionResetError),
            self.assertRaises(WebSocketClosedError),
        ):
            await self.protocol.write_message('hello')

    async def test_write_ping_sends_control_frame(self):
        """The protocol should have the possibility to send a ping control frame."""
        ping_data = b'ping data'
        with patch.object(WebSocketProtocol13, '_write_frame', AsyncMock()) as mock_write_frame:
            await self.protocol.write_ping(ping_data)

        mock_write_frame.assert_awaited_once_with(True, Opcode.PING, ping_data)

    async def test_write_frame_encodes_short_payload_length(self):
        """The frame writer should encode short payload length with correct flags."""
        data = b'data'
        await self.protocol._write_frame(fin=True, opcode=Opcode.TEXT, data=data)

        frame = self.writer.write.call_args_list[-1].args[0]
        first_byte, second_byte = frame[0], frame[1]

        self.assertEqual(first_byte & BitMask.OPCODE, Opcode.TEXT)
        self.assertEqual(second_byte & BitMask.MASK, MaskBit.UNMASKED)
        self.assertEqual(second_byte & BitMask.PAYLOAD_LEN, len(data))

    async def test_write_frame_encodes_short_payload_length_masked(self):
        """The frame writer should encode short payload length with correct flags
        and mask when masked=True.
        """
        data = b'data'
        self.protocol.mask_outgoing = True
        await self.protocol._write_frame(fin=True, opcode=Opcode.TEXT, data=data)

        frame = self.writer.write.call_args_list[-1].args[0]
        first_byte, second_byte = frame[0], frame[1]

        self.assertEqual(first_byte & BitMask.OPCODE, Opcode.TEXT)
        self.assertEqual(second_byte & BitMask.MASK, MaskBit.MASKED)
        self.assertEqual(second_byte & BitMask.PAYLOAD_LEN, len(data))

    async def test_write_frame_encodes_short_payload_length_not_final(self):
        """The frame writer should encode short payload length with FIN flag
        unset for non-final frame.
        """
        data = b'data'
        await self.protocol._write_frame(fin=False, opcode=Opcode.TEXT, data=data)

        frame = self.writer.write.call_args_list[-1].args[0]
        self.assertEqual(frame[0] & BitMask.FINAL, FinalBit.NOT_FINAL)

    async def test_write_frame_encodes_short_payload_length_final(self):
        """The frame writer should encode short payload length correctly."""
        data = b'data'
        await self.protocol._write_frame(fin=True, opcode=Opcode.TEXT, data=data)

        frame = self.writer.write.call_args_list[-1].args[0]
        # Per RFC 6455 Section 5.2, if payload length is between 0 and 125,
        # the 7-bit length is set to the payload length.
        self.assertEqual(frame[1] & BitMask.PAYLOAD_LEN, len(data))

    async def test_write_frame_encodes_extended_16bit_length(self):
        """The frame writer should encode extended 16-bit payload length correctly."""
        data = b'a' * 200
        await self.protocol._write_frame(fin=True, opcode=Opcode.BINARY, data=data)

        frame = self.writer.write.call_args_list[-1].args[0]
        # Per RFC 6455 Section 5.2, if payload length is between 126 and 65535,
        # the 7-bit length is set to 126.
        self.assertEqual(frame[1] & BitMask.PAYLOAD_LEN, 126)

    async def test_write_frame_encodes_extended_64bit_length(self):
        """The frame writer should encode extended 64-bit payload length correctly."""
        data = b'a' * 70000
        await self.protocol._write_frame(fin=True, opcode=Opcode.BINARY, data=data)

        frame = self.writer.write.call_args_list[-1].args[0]
        # Per RFC 6455 Section 5.2, if payload length is 65536 or greater,
        # the 7-bit payload length field is set to 127.
        self.assertEqual(frame[1] & BitMask.PAYLOAD_LEN, 127)

    async def test_write_frame_rejects_fragmented_control(self):
        """The frame writer should have the possibility to reject fragmented control frames."""
        with self.assertRaises(ValueError):
            await self.protocol._write_frame(False, Opcode.PING, b'a')

    async def test_write_frame_rejects_large_control_payload(self):
        """The frame writer should have the possibility to reject control payloads > 125 bytes."""
        with self.assertRaises(ValueError):
            await self.protocol._write_frame(True, Opcode.PING, b'a' * 126)


class TestWebSocketProtocol13Reading(BaseWebSocketTestCase):  # noqa: PLR0904
    """The class implements the tests for reading frames and handling messages."""

    async def test_receive_frame_decodes_text_and_notifies_handler(self):
        """The protocol should have the possibility to decode incoming text frames
        and forward the resulting string to on_message.
        """
        payload = b'payload'
        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.TEXT,
            MaskBit.UNMASKED | len(payload),
        )
        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, payload])),
            patch.object(self.handler, 'on_message', AsyncMock()) as mock_on_message,
        ):
            await self.protocol._receive_frame()

        mock_on_message.assert_awaited_once_with('payload')

    async def test_receive_frame_passes_binary_payload_to_handler(self):
        """The protocol should have the possibility to forward binary frames to
        on_message as bytes.
        """
        payload = b'payload'
        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.BINARY,
            MaskBit.UNMASKED | len(payload),
        )
        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, payload])),
            patch.object(self.handler, 'on_message', AsyncMock()) as mock_on_message,
        ):
            await self.protocol._receive_frame()

        mock_on_message.assert_awaited_once_with(payload)

    async def test_receive_frame_aborts_on_invalid_utf8(self):
        """The protocol should have the possibility to abort the connection when
        a text frame payload fails UTF-8 decoding.
        """
        payload = b'\xff\xff'  # invalid UTF-8 byte sequence
        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.TEXT,
            MaskBit.UNMASKED | len(payload),
        )
        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, payload])),
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
        ):
            await self.protocol._receive_frame()

        mock_abort.assert_awaited()

    async def test_receive_frame_replies_to_ping_and_notifies_handler(self):
        """The protocol should have the possibility to respond to ping frames with pong
        and invoke handler.on_ping.
        """
        payload = b'ping'
        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.PING,
            MaskBit.UNMASKED | len(payload),
        )
        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, payload])),
            patch.object(self.protocol, '_write_frame', AsyncMock()),
            patch.object(self.handler, 'on_ping', AsyncMock()) as mock_on_ping,
        ):
            await self.protocol._receive_frame()

        mock_on_ping.assert_awaited_once_with(payload)

    async def test_receive_frame_marks_pong_received_and_calls_handler(self):
        """The protocol should have the possibility to set the received pong flag and
        notify handler.on_pong.
        """
        payload = b'pong'
        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.PONG,
            MaskBit.UNMASKED | len(payload),
        )
        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, payload])),
            patch.object(self.handler, 'on_pong', AsyncMock()) as mock_on_pong,
        ):
            await self.protocol._receive_frame()

        mock_on_pong.assert_awaited_once_with(payload)
        self.assertTrue(self.protocol._received_pong)

    async def test_receive_frame_appends_continuation_and_delivers_assembled_message(self):
        """The protocol should have the possibility to append continuation frames to
        the buffered message and dispatch the complete payload.
        """
        # Simulate an ongoing fragmented message
        payload1 = b'payload1'
        self.protocol._fragmented_message_buffer = bytearray(payload1)
        self.protocol._fragmented_message_opcode = Opcode.TEXT

        payload2 = b'payload2'
        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.CONTINUATION,
            MaskBit.UNMASKED | len(payload2),
        )

        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, payload2])),
            patch.object(self.protocol, '_handle_message') as mock_handle_message,
            patch.object(self.handler, 'on_message'),
        ):
            await self.protocol._receive_frame()

        self.assertEqual(self.protocol._fragmented_message_opcode, Opcode.TEXT)
        mock_handle_message.assert_called_once_with(Opcode.TEXT, bytearray(payload1 + payload2))
        self.assertIsNone(self.protocol._fragmented_message_buffer)

    async def test_receive_frame_processes_close_and_records_code_reason(self):
        """The protocol should have the possibility to process close frames by invoking close
        with the received code and storing the close code and reason.
        """
        code = 1001
        reason = 'bye'
        payload = struct.pack('>H', code) + reason.encode()

        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.CLOSE,
            MaskBit.UNMASKED | len(payload),
        )
        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, payload])),
            patch.object(self.protocol, 'close', AsyncMock()) as mock_close,
        ):
            await self.protocol._receive_frame()

        mock_close.assert_awaited_once_with(code)
        self.assertEqual(self.protocol.close_code, 1001)
        self.assertEqual(self.protocol.close_reason, reason)

    async def test_receive_frame_aborts_when_reserved_bits_set(self):
        """The protocol should have the possibility to abort the connection when undefined
        reserved bits appear in the header.
        """
        payload = ''
        header = struct.pack(
            'BB',
            FinalBit.FINAL | WebSocketProtocol13.RSV2 | Opcode.TEXT,
            MaskBit.UNMASKED | len(payload),
        )
        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, payload])),
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
        ):
            await self.protocol._receive_frame()

        mock_abort.assert_awaited_once()

    async def test_receive_frame_aborts_on_fragmented_control_frame(self):
        """The protocol should abort on fragmented control frames."""
        header = struct.pack(
            'BB',
            FinalBit.NOT_FINAL | Opcode.PING,
            MaskBit.UNMASKED | len(b''),
        )
        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, ''])),
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
        ):
            await self.protocol._receive_frame()

        mock_abort.assert_awaited_once()

    async def test_receive_frame_aborts_on_control_payload_exceeding_125_bytes(self):
        """The protocol should abort on control frames whose payload length reaches 126 bytes."""
        payload = b'a' * 126
        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.PING,
            MaskBit.UNMASKED | len(payload),
        )
        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header])),
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
        ):
            await self.protocol._receive_frame()

        mock_abort.assert_awaited_once()

    async def test_receive_frame_reads_extended_length_for_16_bit_payloads(self):
        """The protocol should have the possibility to read the additional 16-bit length
        field when the payload length indicator equals 126.
        """
        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.TEXT,
            # Per RFC 6455 Section 5.2, if payload length is between 126 and 65535,
            # the 7-bit length is set to 126.
            MaskBit.UNMASKED | 126,
        )

        payload = b'a' * 130
        extended_len = struct.pack('!H', len(payload))
        with (
            patch.object(self.protocol, '_handle_message'),
            patch.object(
                self.protocol,
                '_read_bytes',
                AsyncMock(side_effect=[header, extended_len, payload]),
            ) as mock_read_bytes,
        ):
            await self.protocol._receive_frame()

        self.assertIs(mock_read_bytes.await_count, 3)
        # The second call to this method relates to reading the next 2 bytes,
        # which according to the standard contain the real payload length
        self.assertEqual(mock_read_bytes.await_args_list[1].args, (2, ))
        self.assertEqual(mock_read_bytes.await_args_list[2].args, (len(payload), ))

    async def test_receive_frame_reads_extended_length_for_64_bit_payloads(self):
        """The protocol should have the possibility to read the additional 64-bit length
        field when the payload length indicator equals 127.
        """
        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.TEXT,
            # Per RFC 6455 Section 5.2, if payload length is 65536 or greater,
            # the 7-bit payload length field is set to 127.
            MaskBit.UNMASKED | 127,
        )

        payload = b'a' * 70000
        extended_len = struct.pack('!Q', len(payload))
        with (
            patch.object(self.protocol, '_handle_message'),
            patch.object(
                self.protocol,
                '_read_bytes',
                AsyncMock(side_effect=[header, extended_len, payload]),
            ) as mock_read_bytes,
        ):
            await self.protocol._receive_frame()

        self.assertIs(mock_read_bytes.await_count, 3)
        # The second call to this method relates to reading the next 8 bytes,
        # which according to the standard contain the real payload length
        self.assertEqual(mock_read_bytes.await_args_list[1].args, (8, ))
        self.assertEqual(mock_read_bytes.await_args_list[2].args, (len(payload), ))

    async def test_receive_frame_aborts_on_unexpected_continuation(self):
        """The protocol should abort if it receives a continuation frame without a
        preceding data frame.
        """
        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.CONTINUATION,
            MaskBit.UNMASKED | len(b''),
        )
        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, ''])),
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
        ):
            await self.protocol._receive_frame()

        mock_abort.assert_awaited_once()

    async def test_receive_frame_aborts_on_new_data_frame_before_fragment_finished(self):
        """The protocol should abort if a new non-final data frame arrives while the previous
        fragmented message is still in progress.
        """
        first = struct.pack(
            'BB',
            FinalBit.NOT_FINAL | Opcode.TEXT,
            MaskBit.UNMASKED | len(b'a'),
        )
        first_header, first_payload = first[:2], first[2:]
        second = struct.pack(
            'BB',
            FinalBit.NOT_FINAL | Opcode.BINARY,
            MaskBit.UNMASKED | len(b'b'),
        )
        second_header, second_payload = second[:2], second[2:]
        with (
            patch.object(
                self.protocol,
                '_read_bytes',
                AsyncMock(side_effect=[first_header, first_payload, second_header, second_payload]),
            ),
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
        ):
            await self.protocol._receive_frame()
            await self.protocol._receive_frame()

        mock_abort.assert_awaited_once()

    async def test_receive_frame_closes_with_1009_when_message_exceeds_limit(self):
        """The protocol should have the possibility to close with 1009 and abort when
        a payload exceeds the configured message size.
        """
        payload = b'data'
        params = get_params(max_message_size=3)
        self.protocol = WebSocketProtocol13(
            self.handler,
            False,
            params,
            self.reader,
            self.writer,
        )

        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.TEXT,
            MaskBit.UNMASKED | len(payload),
        )
        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, payload])),
            patch.object(self.protocol, 'close', AsyncMock()) as mock_close,
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
        ):
            await self.protocol._receive_frame()

        mock_close.assert_awaited_once_with(1009, 'message too big')
        mock_abort.assert_awaited()

    async def test_receive_frame_decompresses_text_when_rsv1_set(self):
        """The protocol should have the possibility to decompress text frames flagged with RSV1
        when a decompressor is configured.
        """
        payload = 'payload'
        compressed_payload = 'compressed payload'

        class _Decompressor:
            @staticmethod
            def decompress(_data):
                return compressed_payload.encode()

        self.protocol._decompressor = _Decompressor()
        header = struct.pack(
            'BB',
            FinalBit.FINAL | WebSocketProtocol13.RSV1 | Opcode.TEXT,
            MaskBit.UNMASKED | len(payload),
        )
        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, payload])),
            patch.object(self.handler, 'on_message', AsyncMock()) as mock_on_message,
        ):
            await self.protocol._receive_frame()

        mock_on_message.assert_awaited_once_with(compressed_payload)

    async def test_receive_frame_handles_decompress_too_large_error(self):
        """The protocol should have the possibility to close with 1009 and abort when
        decompressed payload size exceeds the limit.
        """
        class _Decompressor:
            @staticmethod
            def decompress(_data):
                raise _DecompressTooLargeError

        self.protocol._decompressor = _Decompressor()
        payload = ''
        header = struct.pack(
            'BB',
            FinalBit.FINAL | WebSocketProtocol13.RSV1 | Opcode.TEXT,
            MaskBit.UNMASKED | len(payload),
        )
        with (
            patch.object(self.protocol, 'close', AsyncMock()) as mock_close,
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, payload])),
        ):
            await self.protocol._receive_frame()

        mock_close.assert_awaited()
        mock_abort.assert_awaited()

    async def test_receive_frame_loop_aborts_on_connection_reset_and_notifies_handler(self):
        """The protocol should have the possibility to abort on ConnectionResetError and
        call handler.on_ws_connection_close.
        """
        with (
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
            patch.object(
                self.handler, 'on_ws_connection_close', AsyncMock(),
            ) as mock_on_ws_connection_close,
            patch.object(
                self.protocol, '_receive_frame', AsyncMock(side_effect=ConnectionResetError),
            ),
        ):
            await self.protocol._receive_frame_loop()

        mock_abort.assert_awaited_once()
        mock_on_ws_connection_close.assert_awaited_once()

    async def test_read_bytes_updates_wire_bytes_in_counter(self):
        """The method should have the possibility to read exactly N bytes and update
        the wire-in counter.
        """
        data1 = b'123'
        data2 = b'45'
        self.reader.readexactly = AsyncMock(side_effect=[data1, data2])

        self.assertEqual(self.protocol._wire_bytes_in, 0)

        bytes1 = await self.protocol._read_bytes(3)
        self.assertEqual(bytes1, data1)
        self.assertEqual(self.protocol._wire_bytes_in, len(data1))

        bytes2 = await self.protocol._read_bytes(2)
        self.assertEqual(bytes2, data2)
        self.assertEqual(self.protocol._wire_bytes_in, len(data1) + len(data2))

        self.reader.readexactly.assert_has_awaits([unittest.mock.call(3), unittest.mock.call(2)])

    async def test_receive_frame_unmasks_payload_with_mask_key(self):
        """The protocol should correctly unmask payloads using the 4-byte masking key."""
        payload = b'data'
        mask = b'\xFF\x00\xFF\x00'
        masked_payload = _websocket_mask_python(mask, payload)

        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.BINARY,
            MaskBit.MASKED | len(masked_payload),
        )

        with (
            patch.object(self.handler, 'on_message', AsyncMock()) as mock_on_message,
            patch.object(
                self.protocol,
                '_read_bytes',
                AsyncMock(side_effect=[header, mask, masked_payload]),
            ),
        ):
            await self.protocol._receive_frame()

        mock_on_message.assert_awaited_once_with(payload)

    async def test_receive_frame_aborts_when_pong_write_raises_connection_reset(self):
        """The protocol should abort the connection when replying to ping fails with
        ConnectionResetError.
        """
        payload = b'ping'
        header = struct.pack(
            'BB',
            FinalBit.FINAL | Opcode.PING,
            MaskBit.UNMASKED | len(payload),
        )

        with (
            patch.object(self.protocol, '_read_bytes', AsyncMock(side_effect=[header, payload])),
            patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort,
            patch.object(self.handler, 'on_ping', AsyncMock()) as mock_on_ping,
            patch.object(
                self.protocol, '_write_frame', AsyncMock(side_effect=ConnectionResetError()),
            ),
        ):
            await self.protocol._receive_frame()

        mock_abort.assert_awaited_once()
        mock_on_ping.assert_awaited_once_with(payload)

    async def test_handle_message_returns_none_when_client_already_terminated(self):
        """The protocol should return None from _handle_message when client termination
        has already been recorded.
        """
        self.protocol.client_terminated = True

        result = await self.protocol._handle_message(Opcode.TEXT, b'hello')
        self.assertIsNone(result)

    async def test_handle_message_aborts_on_unknown_opcode(self):
        """The protocol should abort when receiving an unknown opcode in _handle_message."""
        unknown_opcode = 0xB
        with patch.object(self.protocol, '_abort', AsyncMock()) as mock_abort:
            result = await self.protocol._handle_message(unknown_opcode, b'data')

        mock_abort.assert_awaited_once()
        self.assertIsNone(result)


class TestWebSocketProtocol13PeriodicPinging(BaseWebSocketTestCase):
    """The class implements the tests of periodic pinging and its helpers."""

    async def test_periodic_ping_sends_ping_and_handles_timeout(self):
        """periodic_ping should send a ping and close the connection if pong
        is not received in time.
        """
        protocol = WebSocketProtocol13(
            self.handler,
            False,
            get_params(ping_interval=5, ping_timeout=5),
            self.reader,
            self.writer,
        )

        call_num = count()

        def write_ping_side_effect(_data):
            if next(call_num) == 0:
                protocol._received_pong = True

        with (
            patch.object(
                protocol, 'write_ping',
                AsyncMock(side_effect=write_ping_side_effect),
            ),
            patch.object(protocol, 'close', AsyncMock()) as mock_close,
            patch.object(
                protocol, 'ping_sleep_time',
                Mock(return_value=0),
            ) as mock_ping_sleep_time,
            patch('kate.core.websocket.time.time', side_effect=[1, 2, 3]),
            patch('asyncio.sleep', AsyncMock()),
        ):
            await protocol.periodic_ping()

        mock_close.assert_awaited_once_with(reason='ping timed out')
        mock_ping_sleep_time.assert_called_once_with(last_ping_time=1, interval=5, now=2)

    def test_ping_interval_defaults_to_zero_if_none(self):
        """If interval is None, should default to 0."""
        protocol = WebSocketProtocol13(
            self.handler,
            False,
            get_params(ping_interval=None, ping_timeout=0.0),
            self.reader,
            self.writer,
        )
        self.assertEqual(protocol.ping_interval, 0)
        self.assertEqual(protocol.ping_timeout, 0.0)

    def test_ping_sleep_time_computes_next_delay(self):
        """The protocol should have the possibility to compute the sleep time
        until the next ping.
        """
        self.assertEqual(
            WebSocketProtocol13.ping_sleep_time(last_ping_time=100.0, interval=10.0, now=104.0),
            6.0,
        )

    def test_ping_timeout_and_interval_respect_smaller_timeout(self):
        """When timeout is less than interval, values should be used directly."""
        protocol = WebSocketProtocol13(
            self.handler,
            False,
            get_params(ping_interval=10.0, ping_timeout=5.0),
            self.reader,
            self.writer,
        )
        self.assertEqual(protocol.ping_interval, 10.0)
        self.assertEqual(protocol.ping_timeout, 5.0)

    def test_ping_timeout_clamped_to_interval_when_timeout_exceeds_interval(self):
        """Timeout greater than ping interval should be clamped to interval."""
        protocol = WebSocketProtocol13(
            self.handler,
            False,
            get_params(ping_interval=5.0, ping_timeout=10.0),
            self.reader,
            self.writer,
        )
        self.assertEqual(protocol.ping_interval, 5.0)
        self.assertEqual(protocol.ping_timeout, 5.0)

    def test_ping_timeout_defaults_to_interval_if_none(self):
        """If timeout is None, should default to interval value."""
        protocol = WebSocketProtocol13(
            self.handler,
            False,
            get_params(ping_interval=0.0, ping_timeout=None),
            self.reader,
            self.writer,
        )
        self.assertEqual(protocol.ping_interval, 0.0)
        self.assertEqual(protocol.ping_timeout, protocol.ping_interval)

    def test_start_pinging_starts_task_only_once(self):
        """start_pinging should schedule the periodic_ping task only once and
        not duplicate on repeated calls.
        """
        protocol = WebSocketProtocol13(
            self.handler,
            False,
            get_params(ping_interval=10.0, ping_timeout=5.0),
            self.reader,
            self.writer,
        )

        with (
            patch('asyncio.create_task') as mock_create_task,
            patch.object(protocol, 'periodic_ping', Mock()),
        ):
            protocol.start_pinging()
            self.assertIsNotNone(protocol._ping_coroutine)
            self.assertTrue(mock_create_task.called)

            mock_create_task_call_count = mock_create_task.call_count
            old_task = protocol._ping_coroutine

            protocol.start_pinging()
            self.assertEqual(mock_create_task.call_count, mock_create_task_call_count)
            self.assertIs(protocol._ping_coroutine, old_task)


class TestWebSocketProtocol13Compression(BaseWebSocketTestCase):
    """The class implements the tests for WebSocket compression functionality."""

    def test_get_compressor_options_server_role_values(self):
        """The protocol should be able to derive max_wbits and compression_options
        from the server_* keys.
        """
        options = self.protocol._get_compressor_options(
            'server',
            agreed_parameters={'server_max_window_bits': '10'},
            compression_options={'level': 3},
        )
        self.assertEqual(options['max_wbits'], 10)
        self.assertTrue(options['persistent'])
        self.assertEqual(options['compression_options'], {'level': 3})

    def test_get_compressor_options_server_role_no_context_takeover(self):
        """The protocol should have the possibility to disable persistence with
        server_no_context_takeover and return correct max_wbits.
        """
        options = self.protocol._get_compressor_options(
            'server',
            agreed_parameters={'server_no_context_takeover': None},
            compression_options=None,
        )
        self.assertFalse(options['persistent'])

    def test_get_compressor_options_client_role_max_window_bits(self):
        """The protocol should be able to derive client max_wbits and persistent
        from client_max_window_bits.
        """
        options = self.protocol._get_compressor_options(
            'client',
            agreed_parameters={'client_max_window_bits': '12'},
            compression_options={'mem_level': 8},
        )
        self.assertEqual(options['max_wbits'], 12)
        self.assertTrue(options['persistent'])
        self.assertEqual(options['compression_options'], {'mem_level': 8})

    def test_get_compressor_options_client_role_no_context_takeover(self):
        """The protocol should have the possibility to compute client options from
        client_no_context_takeover.
        """
        options = self.protocol._get_compressor_options(
            'client',
            agreed_parameters={'client_no_context_takeover': None},
            compression_options=None,
        )
        self.assertFalse(options['persistent'])

    def test_get_compressor_options_defaults_when_values_absent(self):
        """The protocol should have the possibility to provide default values when bits and
        options are not present.
        """
        options = self.protocol._get_compressor_options(
            'server',
            agreed_parameters={},
            compression_options=None,
        )
        self.assertIsNone(options['compression_options'])
        self.assertIs(options['max_wbits'], 15)
        self.assertTrue(options['persistent'])

    def test_create_compressors_initializes_members_and_roundtrips_payload(self):
        """The protocol should have the possibility to create compressor and decompressor
        that can roundtrip payloads.
        """
        agreed_parameters = {'server_max_window_bits': '12'}  # minimal valid negotiation
        self.protocol._create_compressors(
            'server',
            agreed_parameters=agreed_parameters,
            compression_options={'level': 1},
        )

        payload = b'hello websocket' * 50
        compressed = self.protocol._compressor.compress(payload)
        restored = self.protocol._decompressor.decompress(compressed)
        self.assertEqual(restored, payload)

    def test_create_compressors_raises_for_unsupported_parameter(self):
        """The protocol should have the possibility to raise an error for unsupported
        extension parameters.
        """
        with self.assertRaises(ValueError):
            self.protocol._create_compressors('server', {'unknown_param': '1'}, {})

    def test_create_compressors_create_compressor_and_decompressor(self):
        """The protocol should have the possibility to ignore a client_max_window_bits
        parameter without a value.
        """
        agreed_parameters = {'server_max_window_bits': '10'}
        self.protocol._create_compressors('server', agreed_parameters, {})

        self.assertIsNotNone(self.protocol._compressor)
        self.assertIsInstance(self.protocol._compressor, Compressor)

        self.assertIsNotNone(self.protocol._decompressor)
        self.assertIsInstance(self.protocol._decompressor, Decompressor)

    def test_compressor_constructor_rejects_invalid_maximum_window_bits(self):
        """The compressor should have the possibility to reject max_wbits outside of
        the allowed range.
        """
        with self.assertRaises(ValueError):
            Compressor(persistent=True, max_wbits=7)

        with self.assertRaises(ValueError):
            Compressor(persistent=True, max_wbits=zlib.MAX_WBITS + 1)

    def test_compressor_constructor_accepts_valid_max_window_bits_and_sets_persistent_mode(self):
        """The compressor should have the possibility to accept a valid max_wbits and
        configure persistent mode.
        """
        with patch.object(zlib, 'compressobj', Mock()) as mock_compressobj:
            compressor_persistent = Compressor(persistent=True, max_wbits=9)

        self.assertIsNotNone(compressor_persistent._compressor)
        mock_compressobj.assert_called_once_with(GZIP_LEVEL, zlib.DEFLATED, -9, 8)

        compressor_nonpersistent = Compressor(
            persistent=False,
            max_wbits=None,
            compression_options={
                'compression_level': 6,
                'mem_level': 8,
            })
        self.assertIsNone(compressor_nonpersistent._compressor)
        self.assertEqual(compressor_nonpersistent._compression_level, 6)
        self.assertEqual(compressor_nonpersistent._mem_level, 8)

    def test_compressor_compress_trims_zlib_sync_flush_trailer(self):
        """The compressor should have the possibility to trim the zlib sync-flush
        `0x00 0x00 0xff 0xff` trailer.
        """
        compressor = Compressor(persistent=True, max_wbits=15)
        compressed_data = compressor.compress(b'hello world')

        self.assertIsInstance(compressed_data, bytes)
        # zlib appends a 0x00 0x00 0xFF 0xFF trailer on Z_SYNC_FLUSH;
        # WebSocket permessage-deflate requires trimming it.
        self.assertFalse(compressed_data.endswith(b'\x00\x00\xff\xff'))

    def test_compressor_compress_handles_binary_payload(self):
        """The compressor should have the possibility to compress arbitrary binary payloads."""
        binary_payload = bytes(range(256)) * 4
        compressor = Compressor(persistent=False, max_wbits=15)

        compressed_output = compressor.compress(binary_payload)
        self.assertGreater(len(binary_payload), len(compressed_output))

    def test_decompressor_constructor_rejects_invalid_maximum_window_bits(self):
        """The decompressor should have the possibility to reject maximum_window_bits
        outside of the allowed range.
        """
        with self.assertRaises(ValueError):
            Decompressor(persistent=True, max_wbits=7, max_message_size=1024)

        with self.assertRaises(ValueError):
            Decompressor(persistent=True, max_wbits=zlib.MAX_WBITS + 1, max_message_size=1024)

    def test_decompressor_roundtrip_compress_then_decompress_persistent(self):
        """The compressor and decompressor should have the possibility to roundtrip
        the payload in persistent mode.
        """
        payload_message = ('message' * 50).encode('utf-8')
        compressor = Compressor(persistent=True, max_wbits=15)
        decompressor = Decompressor(persistent=True, max_wbits=15, max_message_size=10_000_000)

        compressed_message = compressor.compress(payload_message)
        restored_message = decompressor.decompress(compressed_message)
        self.assertEqual(restored_message, payload_message)

    def test_decompressor_roundtrip_compress_then_decompress_nonpersistent(self):
        """The compressor and decompressor should have the possibility to roundtrip the payload
        in non-persistent mode.
        """
        payload = bytes(range(64)) * 100
        compressor = Compressor(persistent=False, max_wbits=15)
        decompressor = Decompressor(persistent=False, max_wbits=None, max_message_size=10_000_000)

        compressed_message = compressor.compress(payload)
        restored_message = decompressor.decompress(compressed_message)
        self.assertEqual(restored_message, payload)

    def test_decompressor_raises_when_result_exceeds_max_message_size(self):
        """The decompressor should have the possibility to raise when the uncompressed result
        exceeds the configured maximum_message_size.
        """
        payload_message = b'a' * 10_000
        compressor = Compressor(persistent=False, max_wbits=15)
        compressed_message = compressor.compress(payload_message)

        decompressor = Decompressor(persistent=False, max_wbits=15, max_message_size=1024)
        with self.assertRaises(_DecompressTooLargeError):
            decompressor.decompress(compressed_message)

    def test_decompressor_multiple_calls_do_not_leave_unconsumed_tail(self):
        """The decompressor should have the possibility to fully consume input without
        leaving unconsumed tail.
        """
        payload_1 = b'payload_1' * 200
        payload_2 = b'payload_2' * 300

        compressor = Compressor(persistent=True, max_wbits=15)
        decompressor = Decompressor(persistent=True, max_wbits=15, max_message_size=10_000_000)

        compressed_message_1 = compressor.compress(payload_1)
        restored_message_1 = decompressor.decompress(compressed_message_1)
        self.assertEqual(restored_message_1, payload_1)

        compressed_message_2 = compressor.compress(payload_2)
        restored_message_2 = decompressor.decompress(compressed_message_2)
        self.assertEqual(restored_message_2, payload_2)

    def test_decompressor_nonpersistent_creates_new_instance_per_call(self):
        """The decompressor should have the possibility to create a new internal zlib object
        on each call when non-persistent.
        """
        decompressor = Decompressor(persistent=False, max_wbits=15, max_message_size=10_000_000)
        self.assertIsNone(decompressor._decompressor)

        compressor = Compressor(persistent=False, max_wbits=15)
        _ = decompressor.decompress(compressor.compress(b'sample'))
        self.assertIsNone(decompressor._decompressor)
