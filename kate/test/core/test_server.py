"""The module contains the server implementation tests."""

# ruff: noqa: SLF001

import asyncio
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from kate.core.server import BaseServer, Response


class TestBaseServer(unittest.IsolatedAsyncioTestCase):  # noqa: PLR0904
    """The class implements the BaseServer tests."""

    def setUp(self):
        """Set up test fixtures."""
        self.server = BaseServer()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        """Tear down test fixtures."""
        self.temp_dir.cleanup()

    def test_initialization_with_default_parameters(self):
        """The server should be initialized with proper default parameters."""
        server = BaseServer()

        self.assertEqual(server._host, '127.0.0.1')
        self.assertEqual(server._port, 8888)
        self.assertEqual(server._static_path, Path.cwd() / 'frontend' / 'dist')
        self.assertIsNone(server._ssl_context)
        self.assertIsNone(server.handlers)

    def test_initialization_with_custom_parameters(self):
        """The server should be initialized with custom parameters when provided."""
        port = 9999
        host = '127.0.0.2'
        static_path = self.temp_path / 'custom_static'
        server = BaseServer(host=host, port=port, static_path=static_path)

        self.assertEqual(server._static_path, static_path)
        self.assertEqual(server._host, host)
        self.assertEqual(server._port, port)

    def test_initialization_with_ssl_certificates(self):
        """The server should be initialized with SSL context when certificates are provided."""
        cert_file = self.temp_path / 'cert.pem'
        key_file = self.temp_path / 'key.pem'
        cert_file.write_text('test certificate')
        key_file.write_text('test key')

        with patch('ssl.SSLContext.load_cert_chain'):
            server = BaseServer(ssl_cert=cert_file, ssl_key=key_file)

        self.assertIsNotNone(server._ssl_context)
        self.assertIsInstance(server._ssl_context, ssl.SSLContext)

    def test_header_conversion_with_mixed_lines(self):
        """The server should convert HTTP headers to dictionary, ignoring invalid lines."""
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

    def test_header_conversion_with_no_valid_headers(self):
        """The server should return empty dictionary when no valid headers are present."""
        lines = ['Invalid line', 'Another invalid line']
        result = BaseServer._convert_headers_to_dict(lines)
        self.assertEqual(result, {})

    async def test_server_start_with_default_configuration(self):
        """The server should start with default host and port configuration."""
        mock_server = AsyncMock()
        mock_server.serve_forever = AsyncMock()
        mock_server.__aenter__ = AsyncMock(return_value=mock_server)
        mock_server.__aexit__ = AsyncMock(return_value=None)

        host = '127.0.0.1'
        port = 8888
        with (
            patch('asyncio.start_server', AsyncMock(return_value=mock_server)) as mock_start_server,
            patch('kate.core.server.LOGGER') as mock_logger,
        ):
            await self.server.start()

            mock_start_server.assert_awaited_once_with(
                self.server.handle_request, host, port, ssl=None,
            )
            mock_logger.info.assert_called_once_with('Serving on https://%s:%s', host, port)
            mock_server.serve_forever.assert_awaited_once()

    async def test_server_start_with_ssl_configuration(self):
        """The server should start with SSL context when SSL certificates are configured."""
        cert_file = self.temp_path / 'cert.pem'
        key_file = self.temp_path / 'key.pem'
        cert_file.write_text('test certificate')
        key_file.write_text('test key')

        with patch('ssl.SSLContext.load_cert_chain'):
            server = BaseServer(ssl_cert=cert_file, ssl_key=key_file)

        mock_server = AsyncMock()
        mock_server.serve_forever = AsyncMock()
        mock_server.__aenter__ = AsyncMock(return_value=mock_server)
        mock_server.__aexit__ = AsyncMock(return_value=None)

        with (
            patch('asyncio.start_server', AsyncMock(return_value=mock_server)) as mock_start_server
        ):
            await server.start()

            mock_start_server.assert_awaited_once_with(
                server.handle_request, '127.0.0.1', 8888, ssl=server._ssl_context,
            )
            mock_server.serve_forever.assert_awaited_once()

    async def test_mime_type_detection_for_various_file_types(self):
        """The server should detect correct MIME types for various file extensions."""
        writer = AsyncMock()
        static_path = self.temp_path / 'frontend' / 'dist'
        static_path.mkdir(parents=True, exist_ok=True)
        test_cases = [
            ('style.css', b'text/css'),
            ('script.js', b'text/javascript'),
            ('image.png', b'image/png'),
            ('data.json', b'application/json'),
        ]
        server = BaseServer(static_path=static_path)
        for filename, expected_mime in test_cases:
            test_file = static_path / filename
            test_file.write_text('test content')

            writer.reset_mock()
            await server.handle_static_file_request(f'/{filename}', writer)

            call_args = writer.write.call_args[0][0]
            self.assertIn(f'Content-Type: {expected_mime.decode()}'.encode(), call_args)

    async def test_websocket_handling_with_default_handler(self):
        """The server should use default WebSocketHandler when no custom handler is registered."""
        reader = AsyncMock()
        writer = AsyncMock()
        headers = {
            'Sec-Websocket-Key': 'test_key',
            'Sec-Websocket-version': '13',
            'Host': '127.0.0.1:8888',
        }
        path = '/unknown-ws'
        self.server.handlers = {}

        with patch('kate.core.websocket.WebSocketHandler') as mock_ws_handler:
            mock_handler_instance = AsyncMock()
            mock_ws_handler.return_value = mock_handler_instance

            await self.server.handle_websocket(reader, writer, headers, path)

            mock_ws_handler.assert_called_once_with(headers, reader, writer, self.server)
            mock_handler_instance.get.assert_awaited_once_with()

    async def test_http_error_response_generation(self):
        """The server should generate proper HTTP error responses with status and message."""
        writer = AsyncMock()

        await self.server.send_http_error(writer, 404, 'Not Found')

        writer.write.assert_called_once()
        call_args = writer.write.call_args[0][0]
        self.assertIn(b'HTTP/1.1 404', call_args)
        self.assertIn(b'Content-Type: text/plain; charset=utf-8', call_args)
        self.assertIn(b'Not Found', call_args)

        writer.drain.assert_awaited_once()
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_request_handling_with_incomplete_read_error(self):
        """The server should handle IncompleteReadError gracefully by closing connection."""
        reader = AsyncMock()
        writer = AsyncMock()
        reader.readuntil.side_effect = asyncio.IncompleteReadError(b'', 10)

        result = await self.server.handle_request(reader, writer)

        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()
        self.assertIsNone(result)

    async def test_http_error_handling_with_connection_reset(self):
        """The server should handle ConnectionResetError when sending HTTP error responses."""
        writer = AsyncMock()
        writer.wait_closed.side_effect = ConnectionResetError

        result = await self.server.send_http_error(writer, 404, 'Not found')

        writer.wait_closed.assert_awaited_once()
        self.assertIsNone(result)

    async def test_websocket_upgrade_request_handling(self):
        """The server should handle WebSocket upgrade requests and delegate to WebSocket handler."""
        reader = AsyncMock()
        writer = AsyncMock()
        request_data = (
            b'GET /test_ws HTTP/1.1\r\n'
            b'Host: localhost\r\n'
            b'Upgrade: websocket\r\n'
            b'Connection: Upgrade\r\n'
            b'Sec-WebSocket-Key: 000\r\n'
            b'Sec-WebSocket-Version: 13\r\n'
            b'\r\n'
        )
        reader.readuntil.return_value = request_data

        with patch.object(self.server, 'handle_websocket', AsyncMock()) as mock_handle_ws:
            await self.server.handle_request(reader, writer)

            headers = self.server._convert_headers_to_dict(
                request_data.decode(errors='replace').split('\r\n')[1:],
            )
            mock_handle_ws.assert_awaited_once_with(reader, writer, headers, '/test_ws')

    async def test_upgrade_header_handling_for_websocket_requests(self):
        """The server should route any upgrade header to WebSocket handler regardless of value."""
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

        with (
            patch.object(self.server, 'handle_websocket', AsyncMock()) as mock_handle_ws,
             patch.object(self.server, 'send_http_error', AsyncMock()) as mock_send_error,
        ):
            await self.server.handle_request(reader, writer)

            mock_handle_ws.assert_awaited_once()
            mock_send_error.assert_not_called()

    async def test_non_get_method_request_handling(self):
        """The server should reject non-GET methods with 405 Method Not Allowed error."""
        reader = AsyncMock()
        writer = AsyncMock()
        request_data = (
            b'POST / HTTP/1.1\r\n'
            b'Host: localhost\r\n'
            b'\r\n'
        )
        reader.readuntil.return_value = request_data

        with patch.object(self.server, 'send_http_error', AsyncMock()) as mock_send_error:
            await self.server.handle_request(reader, writer)

            mock_send_error.assert_awaited_once_with(writer, 405, 'Method Not Allowed')

    async def test_static_file_serving_for_index_html(self):
        """The server should serve index.html file when root path is requested."""
        writer = AsyncMock()
        static_path = self.temp_path / 'frontend' / 'dist'
        static_path.mkdir(parents=True, exist_ok=True)

        server = BaseServer(static_path=static_path)
        index_file = static_path / 'index.html'
        index_file.write_text('<html><body>Hello</body></html>')

        await server.handle_static_file_request('/', writer)

        call_args = writer.write.call_args[0][0]
        self.assertIn(b'HTTP/1.1 200 OK', call_args)
        self.assertIn(b'Content-Type: text/html', call_args)
        self.assertIn(b'<html><body>Hello</body></html>', call_args)
        writer.write.assert_called_once()
        writer.drain.assert_awaited_once()

    async def test_static_file_serving_for_existing_files(self):
        """The server should serve existing static files with proper content type."""
        writer = AsyncMock()
        static_path = self.temp_path / 'frontend' / 'dist'
        static_path.mkdir(parents=True, exist_ok=True)

        server = BaseServer(static_path=static_path)
        test_file = static_path / 'test.js'
        test_file.write_text('console.log("test");')

        await server.handle_static_file_request('/test.js', writer)

        writer.write.assert_called_once()
        call_args = writer.write.call_args[0][0]
        self.assertIn(b'HTTP/1.1 200 OK', call_args)
        self.assertTrue(b'Content-Type: text/javascript' in call_args)
        self.assertIn(b'console.log("test");', call_args)

    async def test_static_file_handling_for_nonexistent_files(self):
        """The server should return 404 error when requested static file does not exist."""
        writer = AsyncMock()
        static_path = self.temp_path / 'frontend' / 'dist'
        static_path.mkdir(parents=True, exist_ok=True)
        server = BaseServer(static_path=static_path)

        await server.handle_static_file_request('/nonexistent.txt', writer)

        call_args = writer.write.call_args[0][0]
        self.assertIn(b'HTTP/1.1 404 Not Found', call_args)
        self.assertIn(b'Content-Type: text/plain; charset=utf-8', call_args)
        self.assertIn(b'File not found', call_args)
        writer.write.assert_called_once()
        writer.drain.assert_awaited_once()
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_static_file_path_processing_with_static_prefix(self):
        """The server should remove /static prefix from file paths when serving static files."""
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

    async def test_websocket_handling_with_registered_handler(self):
        """The server should use registered WebSocket handler when available for specific path."""
        reader = AsyncMock()
        writer = AsyncMock()
        headers = {'Sec-WebSocket-Key': 'test_key'}
        path = '/custom-ws'

        mock_handler_class = MagicMock()
        mock_handler_instance = AsyncMock()
        mock_handler_class.return_value = mock_handler_instance
        self.server.handlers = {path: mock_handler_class}

        await self.server.handle_websocket(reader, writer, headers, path)

        mock_handler_class.assert_called_once_with(headers, reader, writer, self.server)
        mock_handler_instance.get.assert_awaited_once_with()

    async def test_websocket_handling_when_handlers_attribute_is_none(self):
        """The server should use default WebSocketHandler when handlers attribute is None."""
        reader = AsyncMock()
        writer = AsyncMock()
        headers = {
            'Sec-WebSocket-Key': 'test_key',
            'Sec-WebSocket-Version': '13',
            'Host': '127.0.0.1:8888',
        }
        path = '/unknown-ws'

        self.server.handlers = None

        with patch('kate.core.websocket.WebSocketHandler') as mock_ws_handler:
            mock_handler_instance = AsyncMock()
            mock_ws_handler.return_value = mock_handler_instance

            await self.server.handle_websocket(reader, writer, headers, path)

            mock_ws_handler.assert_called_once_with(headers, reader, writer, self.server)
            mock_handler_instance.get.assert_awaited_once()

    async def test_concurrent_request_handling(self):
        """The server should handle multiple concurrent requests correctly."""
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


class TestResponse(unittest.TestCase):
    """The class implements the Response tests."""

    def test_response_creation_with_default_values(self):
        """The response should be created with proper default values."""
        response = Response()

        self.assertEqual(response.status, 200)
        self.assertEqual(response.reason, 'OK')
        self.assertEqual(response.body, b'')
        self.assertIn('Connection', response.headers)

    def test_response_creation_with_custom_values(self):
        """The response should accept custom status code, body and headers."""
        response = Response(
            body='test',
            status=201,
            headers={'Custom-Header': 'value'},
        )

        self.assertEqual(response.status, 201)
        self.assertEqual(response.body, b'test')
        self.assertEqual(response.headers['Custom-Header'], 'value')

    def test_response_bytes_conversion_includes_status_line(self):
        """The response should include proper HTTP status line when converted to bytes."""
        response = Response(status=404)
        response_bytes = response.to_bytes()

        self.assertIn(b'404 Not Found', response_bytes)

    def test_response_bytes_conversion_includes_headers(self):
        """The response should include all specified headers when converted to bytes."""
        response = Response(headers={'X-Custom': 'value'})
        response_bytes = response.to_bytes()

        self.assertIn(b'X-Custom: value', response_bytes)
        self.assertIn(b'Content-Length: 0', response_bytes)

    def test_header_setting_modifies_existing_headers(self):
        """The response should allow setting headers which modify existing values."""
        response = Response()
        response.set_header('X-Test', 'value')

        self.assertEqual(response.headers['X-Test'], 'value')

    def test_header_clearing_removes_existing_header(self):
        """The response should allow clearing specific headers."""
        response = Response(headers={'X-Remove': 'value'})
        response.clear_header('X-Remove')

        self.assertNotIn('X-Remove', response.headers)

    def test_status_setting_with_custom_reason(self):
        """The response should allow setting custom status code and reason phrase."""
        response = Response()
        test_reason = 'Test reason'
        test_status = 101
        response.set_status(test_status, test_reason)

        self.assertEqual(test_status, response.status)
        self.assertEqual(test_reason, response.reason)
