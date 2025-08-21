"""The module contains tests for the WebSocket handler implementation."""

import asyncio
import datetime
import unittest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from kate.core.websocket import WebSocketHandler, _WebSocketParams
from kate.core.exceptions import WebSocketClosedError
from kate.core.websocket import httputil


class TestWebSocketHandler(unittest.IsolatedAsyncioTestCase):  # noqa: PLR0904
    """The class implements WebSocket handler tests."""

    def setUp(self):
        super().setUp()
        self.reader = AsyncMock()
        self.writer = Mock()
        self.writer.write = Mock()
        self.writer.drain = AsyncMock()
        self.writer.close = Mock()
        self.writer.wait_closed = AsyncMock()
        self.writer.is_closing = Mock(return_value=False)

        self.headers = {
            'Host': 'example.com',
            'Origin': 'http://example.com',
            'Sec-WebSocket-Version': '13',
            'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ=='
        }

    def create_handler(self, headers=None):
        """Create a WebSocketHandler instance with specified headers."""
        if headers is None:
            headers = self.headers

        return WebSocketHandler(headers, self.reader, self.writer)

    @patch('kate.core.websocket._send_http_error')
    def test_check_origin_valid(self, mock_send_error):
        """The handler should validate origin from trusted domains."""
        handler = self.create_handler()
        result = handler.check_origin('http://example.com')
        self.assertTrue(result)
        mock_send_error.assert_not_called()

    @patch('kate.core.websocket._send_http_error')
    def test_check_origin_invalid(self, mock_send_error):
        """The handler should reject origin from untrusted domains."""
        handler = self.create_handler()
        result = handler.check_origin('http://malicious.com')
        self.assertFalse(result)
        mock_send_error.assert_not_called()

    @patch('kate.core.websocket._send_http_error')
    def test_check_origin_missing(self, mock_send_error):
        """The handler should handle missing origin header."""
        handler = self.create_handler()
        headers = self.headers.copy()
        headers.pop('Origin', None)
        handler.headers = headers

        result = handler.check_origin(None)
        self.assertFalse(result)

    @patch('kate.core.websocket._send_http_error')
    async def test_get_invalid_origin(self, mock_send_error):
        """The handler should reject WebSocket connection from invalid origin."""
        headers = self.headers.copy()
        headers['Origin'] = 'http://malicious.com'
        handler = self.create_handler(headers)

        await handler.get()
        mock_send_error.assert_called_once_with(
            self.writer, 403, 'Cross origin websockets not allowed'
        )

    @patch('kate.core.websocket._send_http_error')
    async def test_get_invalid_version(self, mock_send_error):
        """The handler should reject unsupported WebSocket versions."""
        headers = self.headers.copy()
        headers['Sec-WebSocket-Version'] = '12'
        handler = self.create_handler(headers)

        await handler.get()
        mock_send_error.assert_called_once_with(
            self.writer, 426, 'Upgrade Required'
        )

    @patch('kate.core.websocket.WebSocketHandler.get_websocket_protocol')
    async def test_get_success(self, mock_get_protocol):
        """The handler should successfully complete WebSocket handshake."""
        mock_protocol = AsyncMock()
        mock_protocol.accept_connection = AsyncMock()
        mock_get_protocol.return_value = mock_protocol

        handler = self.create_handler()
        await handler.get()

        mock_get_protocol.assert_called_once()
        mock_protocol.accept_connection.assert_called_once_with(
            self.headers, handler
        )

    async def test_write_message_text(self):
        """The handler should send text messages through WebSocket connection."""
        handler = self.create_handler()
        handler.ws_connection = AsyncMock()
        handler.ws_connection.write_message = AsyncMock()
        handler.ws_connection.is_closing = Mock(return_value=False)

        await handler.write_message("Hello")
        handler.ws_connection.write_message.assert_called_once_with(
            "Hello", binary=False
        )

    async def test_write_message_binary(self):
        """The handler should send binary messages through WebSocket connection."""
        handler = self.create_handler()
        handler.ws_connection = AsyncMock()
        handler.ws_connection.write_message = AsyncMock()
        handler.ws_connection.is_closing = Mock(return_value=False)

        await handler.write_message(b"Hello", binary=True)
        handler.ws_connection.write_message.assert_called_once_with(
            b"Hello", binary=True
        )

    async def test_write_message_dict(self):
        """The handler should serialize and send JSON messages."""
        handler = self.create_handler()
        handler.ws_connection = AsyncMock()
        handler.ws_connection.write_message = AsyncMock()
        handler.ws_connection.is_closing = Mock(return_value=False)

        await handler.write_message({"key": "value"})
        handler.ws_connection.write_message.assert_called_once_with(
            '{"key": "value"}', binary=False
        )

    async def test_write_message_closed(self):
        """The handler should raise error when writing to closed connection."""
        handler = self.create_handler()
        handler.ws_connection = AsyncMock()
        handler.ws_connection.is_closing = Mock(return_value=True)

        with self.assertRaises(WebSocketClosedError):
            await handler.write_message("Hello")

    async def test_ping(self):
        """The handler should send ping messages through WebSocket connection."""
        handler = self.create_handler()
        handler.ws_connection = Mock()
        handler.ws_connection.is_closing.return_value = False
        handler.ws_connection.write_ping = Mock()

        handler.ping(b"ping")
        handler.ws_connection.write_ping.assert_called_once_with(b"ping")

    async def test_ping_closed(self):
        """The handler should raise error when pinging closed connection."""
        handler = self.create_handler()
        handler.ws_connection = Mock()
        handler.ws_connection.is_closing.return_value = True

        with self.assertRaises(WebSocketClosedError):
            handler.ping(b"ping")

    async def test_close(self):
        """The handler should close WebSocket connection properly."""
        handler = self.create_handler()
        handler.ws_connection = AsyncMock()
        handler.ws_connection.close = AsyncMock()

        await handler.close(1000, "Normal closure")
        self.assertIsNone(handler.ws_connection)

    async def test_on_connection_close_normal(self):
        """The handler should handle normal connection closure."""
        handler = self.create_handler()
        handler.ws_connection = AsyncMock()
        handler.ws_connection.on_connection_close = AsyncMock()
        handler.on_close = Mock()

        await handler.on_connection_close()

        handler.on_close.assert_called_once()
        self.assertIsNone(handler.ws_connection)
        self.assertTrue(handler._on_close_called)

    async def test_on_connection_close_no_connection(self):
        """The handler should handle connection closure when ws_connection is None."""
        handler = self.create_handler()
        handler.ws_connection = None
        handler.on_close = Mock()

        await handler.on_connection_close()

        handler.on_close.assert_called_once()
        self.assertTrue(handler._on_close_called)

    async def test_on_ws_connection_close(self):
        """The handler should handle WebSocket connection closure with code and reason."""
        handler = self.create_handler()
        handler.on_connection_close = AsyncMock()

        await handler.on_ws_connection_close(1001, "Going away")

        self.assertEqual(handler.close_code, 1001)
        self.assertEqual(handler.close_reason, "Going away")
        handler.on_connection_close.assert_called_once()

    def test_select_subprotocol(self):
        """The handler should select appropriate subprotocol from client options."""
        handler = self.create_handler()
        result = handler.select_subprotocol(["proto1", "proto2"])
        self.assertIsNone(result)

    def test_get_compression_options(self):
        """The handler should return compression options for WebSocket connection."""
        handler = self.create_handler()
        result = handler.get_compression_options()
        self.assertIsNone(result)

    def test_selected_subprotocol(self):
        """The handler should return selected subprotocol."""
        handler = self.create_handler()
        handler.ws_connection = Mock()
        handler.ws_connection.selected_subprotocol = "goodproto"

        self.assertEqual(handler.selected_subprotocol, "goodproto")

    def test_ping_interval(self):
        """The handler should return configured ping interval."""
        handler = self.create_handler()
        handler.settings = {"websocket_ping_interval": 30}
        self.assertEqual(handler.ping_interval, 30)

    def test_ping_timeout(self):
        """The handler should return configured ping timeout."""
        handler = self.create_handler()
        handler.settings = {"websocket_ping_timeout": 10}
        self.assertEqual(handler.ping_timeout, 10)

    def test_max_message_size(self):
        """The handler should return configured maximum message size."""
        handler = self.create_handler()
        handler.settings = {"websocket_max_message_size": 1024}
        self.assertEqual(handler.max_message_size, 1024)

    def test_max_message_size_default(self):
        """The handler should return default maximum message size when not configured."""
        handler = self.create_handler()
        self.assertEqual(handler.max_message_size, 10 * 1024 * 1024)

    @patch('kate.core.websocket.WebSocketProtocol13')
    def test_get_websocket_protocol_valid(self, mock_protocol):
        """The handler should create protocol for valid WebSocket version."""
        mock_protocol_instance = Mock()
        mock_protocol.return_value = mock_protocol_instance

        handler = self.create_handler()
        result = handler.get_websocket_protocol()

        self.assertEqual(result, mock_protocol_instance)
        mock_protocol.assert_called_once()

    def test_get_websocket_protocol_invalid(self):
        """The handler should return None for unsupported WebSocket version."""
        headers = self.headers.copy()
        headers['Sec-WebSocket-Version'] = '99'
        handler = self.create_handler(headers)

        result = handler.get_websocket_protocol()
        self.assertIsNone(result)

    async def test_finish_success(self):
        """The handler should finish response successfully."""
        handler = self.create_handler()

        await handler.finish("Hello")

        self.writer.write.assert_called_once_with(b'Hello')
        self.writer.drain.assert_called_once()
        self.writer.close.assert_called_once()
        self.writer.wait_closed.assert_called_once()
        self.assertTrue(handler._finished)

    async def test_finish_without_chunk(self):
        """The handler should finish response without sending data."""
        handler = self.create_handler()

        await handler.finish()

        self.writer.write.assert_not_called()
        self.writer.drain.assert_not_called()
        self.writer.close.assert_not_called()
        self.writer.wait_closed.assert_not_called()
        self.assertTrue(handler._finished)

    async def test_finish_write_exception(self):
        """The handler should handle write exceptions during finish."""
        handler = self.create_handler()
        self.writer.write.side_effect = Exception("Write error")

        with self.assertRaises(Exception):
            await handler.finish("Hello")

    async def test_finish_called_twice(self):
        """The handler should handle write exceptions during finish."""
        handler = self.create_handler()
        await handler.finish()

        with self.assertRaises(RuntimeError):
            await handler.finish()

    def test_set_header(self):
        """The handler should set response headers correctly."""
        handler = self.create_handler()
        handler.set_header("X-Test", "value")
        self.assertEqual(handler._headers["X-Test"], "value")

    def test_clear_header(self):
        """The handler should clear specified response headers."""
        handler = self.create_handler()
        handler.set_header("X-Test", "value")
        handler.clear_header("X-Test")
        self.assertNotIn("X-Test", handler._headers)

    def test_set_status_without_reason(self):
        """The handler set HTTP status code without reason."""
        handler = self.create_handler()
        handler.set_status(600)
        self.assertEqual(handler._status_code, 600)
        self.assertEqual(handler._reason, "Unknown")

    def test_set_status_with_reason(self):
        """The handler set HTTP status code with reason."""
        handler = self.create_handler()
        handler.set_status(404, "Not Found")
        self.assertEqual(handler._status_code, 404)
        self.assertEqual(handler._reason, "Not Found")

    def test_clear(self):
        """The handler should clear headers and buffers while preserving defaults."""
        handler = self.create_handler()
        handler.set_header("X-Test", "value")
        handler._write_buffer.append(b"test")
        handler._status_code = 404

        handler.clear()

        self.assertEqual(handler._status_code, 200)
        self.assertEqual(handler._reason, "OK")
        self.assertEqual(handler._write_buffer, [])
        self.assertIn("Server", handler._headers)
        self.assertIn("Content-Type", handler._headers)
        self.assertIn("Date", handler._headers)

    def test_convert_header_value_str(self):
        """The handler should convert string header values correctly."""
        handler = self.create_handler()
        result = handler._convert_header_value("test")
        self.assertEqual(result, "test")

    def test_convert_header_value_bytes(self):
        """The handler should convert bytes header values correctly."""
        handler = self.create_handler()
        result = handler._convert_header_value(b"test")
        self.assertEqual(result, "test")

    def test_convert_header_value_int(self):
        """The handler should convert integer header values correctly."""
        handler = self.create_handler()
        result = handler._convert_header_value(42)
        self.assertEqual(result, "42")

    def test_convert_header_value_datetime(self):
        """The handler should convert datetime header values correctly."""
        handler = self.create_handler()
        now = datetime.datetime.now()
        result = handler._convert_header_value(now)
        expected = httputil.format_timestamp(now)
        self.assertEqual(result, expected)

    def test_convert_header_value_invalid(self):
        """The handler should raise error for invalid header value types."""
        handler = self.create_handler()
        with self.assertRaises(TypeError):
            handler._convert_header_value([])

    def test_clear_representation_headers(self):
        """The handler should clear content representation headers."""
        handler = self.create_handler()
        handler.set_header("Content-Encoding", "gzip")
        handler.set_header("Content-Language", "en")
        handler.set_header("Content-Type", "text/html")

        handler._clear_representation_headers()

        self.assertNotIn("Content-Encoding", handler._headers)
        self.assertNotIn("Content-Language", handler._headers)
        self.assertNotIn("Content-Type", handler._headers)


class TestWebSocketParams(unittest.IsolatedAsyncioTestCase):
    """The class implements WebSocket parameters tests."""

    def test_websocket_params(self):
        """The WebSocket parameters should be stored and retrieved correctly."""
        params = _WebSocketParams(
            ping_interval=30,
            ping_timeout=10,
            max_message_size=1024,
            compression_options={"level": 9}
        )

        self.assertEqual(params.ping_interval, 30)
        self.assertEqual(params.ping_timeout, 10)
        self.assertEqual(params.max_message_size, 1024)
        self.assertEqual(params.compression_options, {"level": 9})
