"""The module contains the unit tests for the WebSocketProtocol13 class."""

import asyncio
import base64
import hashlib
import struct
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from kate.core.websocket.protocol import WebSocketProtocol13, _GUID
from kate.core.exceptions import WebSocketClosedError


class TestWebSocketProtocol13(unittest.IsolatedAsyncioTestCase):
    """Test class for WebSocketProtocol13."""

    def setUp(self):
        """Set up test fixtures."""
        self.handler = MagicMock()
        self.reader = AsyncMock()
        self.writer = AsyncMock()
        self.params = MagicMock()
        self.params.compression_options = None
        self.protocol = WebSocketProtocol13(
            self.handler, False, self.params, self.reader, self.writer
        )

    def test_compute_accept_value(self):
        """Test computing WebSocket accept value."""
        key = 'dGhlIHNhbXBsZSBub25jZQ=='
        expected = base64.b64encode(
            hashlib.sha1((key + _GUID).encode()).digest()
        ).decode('utf-8')

        result = WebSocketProtocol13.compute_accept_value(key)
        self.assertEqual(result, expected)

    async def test_accept_connection_success(self):
        """Test successful WebSocket connection acceptance."""
        headers = {
            'Host': 'localhost:8888',
            'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ==',
            'Sec-WebSocket-Version': '13',
        }

        with patch.object(self.protocol, '_handle_websocket_headers'), \
            patch.object(self.protocol, '_accept_connection', AsyncMock()):
            await self.protocol.accept_connection(headers, self.handler)

    async def test_accept_connection_invalid_headers(self):
        """Test WebSocket connection with invalid headers."""
        headers = {'Host': 'localhost:8888'}  # Missing required headers

        with patch('kate.core.websocket.protocol._send_http_error',
                   AsyncMock()) as mock_send_error:
            await self.protocol.accept_connection(headers, self.handler)

            mock_send_error.assert_awaited_once_with(
                self.writer, 400, 'Missing/Invalid WebSocket headers'
            )

    async def test_accept_connection_malformed_request(self):
        """Test WebSocket connection with malformed request."""
        headers = {
            'Host': 'localhost:8888',
            'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ==',
            'Sec-WebSocket-Version': '13',
        }

        with patch.object(self.protocol, '_accept_connection', side_effect=ValueError), \
            patch.object(self.protocol, '_abort', AsyncMock()):
            await self.protocol.accept_connection(headers, self.handler)
            self.protocol._abort.assert_awaited_once()

    def test_handle_websocket_headers_valid(self):
        """Test validating valid WebSocket headers."""
        headers = {
            'Host': 'localhost:8888',
            'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ==',
            'Sec-WebSocket-Version': '13',
        }

        # Should not raise an exception
        WebSocketProtocol13._handle_websocket_headers(headers)

    def test_handle_websocket_headers_invalid(self):
        """Test validating invalid WebSocket headers."""
        headers = {'Host': 'localhost:8888'}  # Missing required headers

        with self.assertRaises(ValueError):
            WebSocketProtocol13._handle_websocket_headers(headers)

    async def test_write_message_success(self):
        """Test successfully writing a message."""
        test_message = 'test message'

        with patch.object(self.protocol, '_write_frame', AsyncMock()):
            await self.protocol.write_message(test_message)

            self.protocol._write_frame.assert_awaited_once()

    async def test_write_message_closed_connection(self):
        """Test writing to a closed connection."""
        self.protocol.client_terminated = True

        with self.assertRaises(WebSocketClosedError):
            await self.protocol.write_message('test message')

    async def test_write_ping(self):
        """Test sending a ping."""
        with patch.object(self.protocol, '_write_frame', AsyncMock()):
            await self.protocol.write_ping(b'test data')

            self.protocol._write_frame.assert_awaited_once_with(True, 0x9, b'test data')

    async def test_close(self):
        """Test closing WebSocket connection."""
        with patch.object(self.protocol, '_write_frame', AsyncMock()), \
            patch.object(self.protocol, '_abort', AsyncMock()):
            await self.protocol.close(1000, 'Normal closure')

            self.protocol._write_frame.assert_awaited_once()
            self.assertTrue(self.protocol.server_terminated)

    async def test_receive_frame_loop_normal(self):
        """Test normal frame reception loop."""
        with patch.object(self.protocol, '_receive_frame', AsyncMock()) as mock_receive_frame:
            mock_receive_frame.side_effect = [None, None, Exception('break loop')]

            try:
                await self.protocol._receive_frame_loop()
            except Exception:
                pass

            self.assertEqual(mock_receive_frame.await_count, 3)

    async def test_receive_frame_loop_closed_connection(self):
        """Test frame reception loop with closed connection."""
        self.protocol.client_terminated = True

        # Should exit immediately without processing frames
        await self.protocol._receive_frame_loop()

    def test_is_closing(self):
        """Test connection closing status."""
        self.assertFalse(self.protocol.is_closing())

        self.protocol.client_terminated = True
        self.assertTrue(self.protocol.is_closing())

        self.protocol.client_terminated = False
        self.protocol.server_terminated = True
        self.assertTrue(self.protocol.is_closing())
