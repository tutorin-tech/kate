"""The module contains the unit tests for the BaseServer class."""

# ruff: noqa: SLF001

import asyncio
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from kate.core.server import BaseServer


class TestBaseServer(unittest.IsolatedAsyncioTestCase):  # noqa: PLR0904
    """Test class for BaseServer."""

    def setUp(self):
        """Set up test fixtures."""
        self.server = BaseServer()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        """Tear down test fixtures."""
        self.temp_dir.cleanup()

    def test_init_default(self):
        """Test BaseServer initialization with default parameters."""
        server = BaseServer()

        self.assertEqual(server._host, '127.0.0.1')
        self.assertEqual(server._port, 8888)
        self.assertEqual(server._static_path, Path.cwd() / 'frontend' / 'dist')
        self.assertIsNone(server._ssl_context)
        self.assertIsNone(server.handlers)

    def test_init_custom_params(self):
        """Test BaseServer initialization with custom parameters."""
        port = 9999
        host = '127.0.0.2'
        static_path = self.temp_path / 'custom_static'
        server = BaseServer(host=host, port=port, static_path=static_path)

        self.assertEqual(server._static_path, static_path)
        self.assertEqual(server._host, host)
        self.assertEqual(server._port, port)

    def test_init_with_ssl(self):
        """Test BaseServer initialization with SSL."""
        cert_file = self.temp_path / 'cert.pem'
        key_file = self.temp_path / 'key.pem'
        cert_file.write_text('test cert')
        key_file.write_text('test key')

        with patch('ssl.SSLContext.load_cert_chain'):
            server = BaseServer(ssl_cert=cert_file, ssl_key=key_file)

        self.assertIsNotNone(server._ssl_context)
        self.assertIsInstance(server._ssl_context, ssl.SSLContext)

    def test_convert_headers_to_dict(self):
        """Test _convert_headers_to_dict static method."""
        lines = [
            'Content-Type: application/json',
            'Content-Length: 100',
            'Authorization: Bearer token123',
            'Invalid line without colon',
            '',
        ]

        result = BaseServer._convert_headers_to_dict(lines)

        expected = {
            'Content-Type': 'application/json',
            'Content-Length': '100',
            'Authorization': 'Bearer token123',
        }
        self.assertEqual(result, expected)

    def test_convert_headers_to_dict_no_colon(self):
        """Test _convert_headers_to_dict with lines without colon."""
        lines = ['Invalid line', 'Another invalid line']
        result = BaseServer._convert_headers_to_dict(lines)
        self.assertEqual(result, {})

    async def test_send_http_error(self):
        """Test _send_http_error method."""
        writer = AsyncMock()

        await BaseServer._send_http_error(writer, 404, 'Not Found')

        writer.write.assert_called_once()
        call_args = writer.write.call_args[0][0]
        self.assertIn(b'HTTP/1.1 404', call_args)
        self.assertIn(b'Content-Type: text/plain', call_args)
        self.assertIn(b'Not Found', call_args)

        writer.drain.assert_awaited_once()
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_handle_request_incomplete_read(self):
        """Test handle_request with incomplete read."""
        reader = AsyncMock()
        writer = AsyncMock()
        reader.readuntil.side_effect = asyncio.IncompleteReadError(b'', 10)

        await self.server.handle_request(reader, writer)

        writer.close.assert_called_once()

    async def test_handle_request_websocket_upgrade(self):
        """Test handle_request with WebSocket upgrade."""
        reader = AsyncMock()
        writer = AsyncMock()
        request_data = (
            b'GET /ws HTTP/1.1\r\n'
            b'Host: localhost\r\n'
            b'Upgrade: websocket\r\n'
            b'Connection: Upgrade\r\n'
            b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
            b'Sec-WebSocket-Version: 13\r\n'
            b'\r\n'
        )
        reader.readuntil.return_value = request_data

        with patch.object(self.server, 'handle_websocket', AsyncMock()) as mock_handle_ws:
            await self.server.handle_request(reader, writer)

            mock_handle_ws.assert_awaited_once()

    async def test_handle_request_invalid_upgrade(self):
        """Test handle_request with invalid upgrade header."""
        reader = AsyncMock()
        writer = AsyncMock()
        request_data = (
            b'GET / HTTP/1.1\r\n'
            b'Host: localhost\r\n'
            b'Upgrade: invalid\r\n'
            b'Connection: Upgrade\r\n'
            b'\r\n'
        )
        reader.readuntil.return_value = request_data

        with patch.object(self.server, '_send_http_error', AsyncMock()) as mock_send_error:
            await self.server.handle_request(reader, writer)

            mock_send_error.assert_awaited_once_with(
                writer,
                400,
                "Can 'Upgrade' only to 'WebSocket'.",
            )

    async def test_handle_request_non_get_method(self):
        """Test handle_request with non-GET method."""
        reader = AsyncMock()
        writer = AsyncMock()
        request_data = (
            b'POST / HTTP/1.1\r\n'
            b'Host: localhost\r\n'
            b'\r\n'
        )
        reader.readuntil.return_value = request_data

        with patch.object(self.server, '_send_http_error', AsyncMock()) as mock_send_error:
            await self.server.handle_request(reader, writer)

            mock_send_error.assert_awaited_once_with(
                writer,
                405,
                'Method Not Allowed',
            )

    async def test_handle_static_file_request_index_html(self):
        """Test handle_static_file_request for index.html."""
        writer = AsyncMock()
        static_path = self.temp_path / 'frontend' / 'dist'
        static_path.mkdir(parents=True, exist_ok=True)

        server = BaseServer(static_path=static_path)
        index_file = static_path / 'index.html'
        index_file.write_text('<html><body>Hello</body></html>')

        await server.handle_static_file_request('/', writer)

        writer.write.assert_called_once()
        call_args = writer.write.call_args[0][0]
        self.assertIn(b'HTTP/1.1 200 OK', call_args)
        self.assertIn(b'Content-Type: text/html', call_args)
        self.assertIn(b'<html><body>Hello</body></html>', call_args)
        writer.drain.assert_awaited_once()
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_handle_static_file_request_existing_file(self):
        """Test handle_static_file_request for existing file."""
        writer = AsyncMock()
        static_path = self.temp_path / 'frontend' / 'dist'
        static_path.mkdir(parents=True, exist_ok=True)

        server = BaseServer(static_path=static_path)
        test_file = static_path / 'test.js'
        test_file.write_text('console.log("hello");')

        await server.handle_static_file_request('/test.js', writer)

        writer.write.assert_called_once()
        call_args = writer.write.call_args[0][0]
        self.assertIn(b'HTTP/1.1 200 OK', call_args)
        self.assertIn(b'Content-Type: text/javascript', call_args)
        self.assertIn(b'console.log("hello");', call_args)

    async def test_handle_static_file_request_nonexistent_file(self):
        """Test handle_static_file_request for non-existent file."""
        writer = AsyncMock()
        static_path = self.temp_path / 'frontend' / 'dist'
        static_path.mkdir(parents=True, exist_ok=True)

        server = BaseServer(static_path=static_path)

        await server.handle_static_file_request('/nonexistent.txt', writer)

        writer.write.assert_called_once_with(
            b'HTTP/1.1 404 Not Found\r\n'
            b'Content-Type: text/plain\r\n'
            b'\r\n'
            b'File not found',
        )
        writer.drain.assert_awaited_once()
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_handle_static_file_request_static_removal(self):
        """Test handle_static_file_request removes /static from path."""
        writer = AsyncMock()
        static_path = self.temp_path / 'frontend' / 'dist'
        static_path.mkdir(parents=True, exist_ok=True)

        server = BaseServer(static_path=static_path)
        test_file = static_path / 'script.js'
        test_file.write_text('test content')

        await server.handle_static_file_request('/static/script.js', writer)

        writer.write.assert_called_once()
        call_args = writer.write.call_args[0][0]
        self.assertIn(b'HTTP/1.1 200 OK', call_args)
        self.assertIn(b'test content', call_args)

    async def test_handle_websocket_with_handler(self):
        """Test handle_websocket with registered handler."""
        reader = AsyncMock()
        writer = AsyncMock()
        headers = {'Sec-WebSocket-Key': 'test_key'}
        path = '/custom-ws'

        mock_handler_class = MagicMock()
        mock_handler_instance = AsyncMock()
        mock_handler_class.return_value = mock_handler_instance

        self.server.handlers = {path: mock_handler_class}

        await self.server.handle_websocket(reader, writer, headers, path)

        mock_handler_class.assert_called_once_with(headers, reader, writer)
        mock_handler_instance.get.assert_awaited_once()

    async def test_handle_websocket_default_handler(self):
        """Test handle_websocket with default WebSocketHandler."""
        reader = AsyncMock()
        writer = AsyncMock()
        headers = {
            'Sec-Websocket-Key': 'test_key',
            'Sec-Websocket-version': '13',
            'Host': '127.0.0.1:8888',
        }
        path = '/unknown-ws'

        self.server.handlers = {}

        with patch('kate.backend.server.WebSocketHandler') as mock_ws_handler:
            mock_handler_instance = AsyncMock()
            mock_ws_handler.return_value = mock_handler_instance

            await self.server.handle_websocket(reader, writer, headers, path)

            mock_ws_handler.assert_called_once_with(headers, reader, writer)
            mock_handler_instance.get.assert_awaited_once()

    async def test_handle_websocket_no_handlers_attribute(self):
        """Test handle_websocket when handlers attribute is None."""
        reader = AsyncMock()
        writer = AsyncMock()
        headers = {
            'Sec-WebSocket-Key': 'test_key',
            'Sec-WebSocket-Version': '13',
            'Host': '127.0.0.1:8888',
        }
        path = '/unknown-ws'

        self.server.handlers = None

        with patch('kate.backend.server.WebSocketHandler') as mock_ws_handler:
            mock_handler_instance = AsyncMock()
            mock_ws_handler.return_value = mock_handler_instance

            await self.server.handle_websocket(reader, writer, headers, path)

            mock_ws_handler.assert_called_once_with(headers, reader, writer)
            mock_handler_instance.get.assert_awaited_once()

    async def test_start_server(self):
        """Test start method."""
        mock_server = AsyncMock()
        mock_server.serve_forever = AsyncMock()
        mock_server.__aenter__ = AsyncMock(return_value=mock_server)
        mock_server.__aexit__ = AsyncMock(return_value=None)

        with (
            patch('asyncio.start_server', AsyncMock(return_value=mock_server)) as mock_start_server,
             patch('kate.backend.server.LOGGER') as mock_logger,
        ):
            await self.server.start()

            mock_start_server.assert_awaited_once_with(
                self.server.handle_request, '127.0.0.1', 8888, ssl=None,
            )
            mock_logger.info.assert_called_once_with(
                'Serving on https://%s:%s', '127.0.0.1', 8888,
            )
            mock_server.serve_forever.assert_awaited_once()

    async def test_start_server_with_ssl(self):
        """Test start method with SSL context."""
        cert_file = self.temp_path / 'cert.pem'
        key_file = self.temp_path / 'key.pem'
        cert_file.write_text('test cert')
        key_file.write_text('test key')

        with patch('ssl.SSLContext.load_cert_chain'):
            server = BaseServer(ssl_cert=cert_file, ssl_key=key_file)

        mock_server = AsyncMock()
        mock_server.serve_forever = AsyncMock()
        mock_server.__aenter__ = AsyncMock(return_value=mock_server)
        mock_server.__aexit__ = AsyncMock(return_value=None)

        with patch(
            'asyncio.start_server',
            AsyncMock(return_value=mock_server),
        ) as mock_start_server:
            await server.start()

            mock_start_server.assert_awaited_once_with(
                server.handle_request, '127.0.0.1', 8888,
                ssl=server._ssl_context,
            )

    async def test_mime_type_detection(self):
        """Test MIME type detection for various file types."""
        writer = AsyncMock()
        static_path = self.temp_path / 'frontend' / 'dist'
        static_path.mkdir(parents=True, exist_ok=True)

        server = BaseServer(static_path=static_path)

        test_cases = [
            ('style.css', 'text/css'),
            ('script.js', 'text/javascript'),
            ('image.png', 'image/png'),
            ('data.json', 'application/json'),
        ]

        for filename, expected_mime in test_cases:
            test_file = static_path / filename
            test_file.write_text('test content')

            writer.reset_mock()
            await server.handle_static_file_request(f'/{filename}', writer)

            call_args = writer.write.call_args[0][0]
            self.assertIn(f'Content-Type: {expected_mime}'.encode(), call_args)

    async def test_concurrent_requests(self):
        """Test handling concurrent requests."""
        static_path = self.temp_path / 'frontend' / 'dist'
        static_path.mkdir(parents=True, exist_ok=True)

        server = BaseServer(static_path=static_path)
        (static_path / 'file1.txt').write_text('content1')
        (static_path / 'file2.txt').write_text('content2')

        async def make_request(_path):
            reader = AsyncMock()
            writer = AsyncMock()

            writer.drain = AsyncMock()
            writer.close = AsyncMock()
            writer.wait_closed = AsyncMock()

            reader.readuntil.return_value = b'GET / HTTP/1.1\r\n\r\n'

            await server.handle_request(reader, writer)
            return writer.write.call_count

        results = await asyncio.gather(
            make_request('/file1.txt'),
            make_request('/file2.txt'),
            make_request('/file1.txt'),
        )
        self.assertTrue(all(count == 1 for count in results))
