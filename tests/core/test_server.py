"""The module contains the tests for the core server module."""

# ruff: noqa: PLR6301, SLF001

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from kate.core.server import BaseServer, Response
from tests.core.base import get_writer


class TestResponse(unittest.TestCase):
    """The class implements the tests for the core Response helper."""

    def test_clear_header_removes_existing_header(self):
        """The response should have the possibility to remove headers that are present."""
        response = Response(headers={'Content-Type': 'text/plain'})
        response.clear_header('Content-Type')

        self.assertNotIn('Content-Type', response.headers)

    def test_set_header_updates_value(self):
        """The response should have the possibility to set or update header values."""
        response = Response()
        response.set_header('Content-Type', 'application/json')

        self.assertEqual('application/json', response.headers['Content-Type'])

    def test_set_status_assigns_reason(self):
        """The response should have the possibility to update status and infer default reason."""
        response = Response()
        response.set_status(404)

        self.assertEqual(404, response.status)
        self.assertEqual('Not Found', response.reason)

    def test_to_bytes_formats_http_response(self):
        """The response should have the possibility to render the response as HTTP bytes."""
        payload = 'payload'
        response = Response(payload, status=201, headers={'X-Test': 'yes'})
        rendered = response.to_bytes()

        head, body = rendered.split(b'\r\n\r\n', 1)
        self.assertIn(b'HTTP/1.1 201 Created', head)
        self.assertIn(b'Content-Length: ' + f'{len(payload)}'.encode(), head)
        self.assertIn(b'X-Test: yes', head)
        self.assertEqual(payload.encode(), body)


class TestServer(unittest.IsolatedAsyncioTestCase):
    """The class implements the BaseServer tests."""

    def setUp(self):
        """Set up the test environment."""
        self.server = BaseServer()
        self.reader = AsyncMock()
        self.writer = get_writer()

    def test_convert_headers_to_dict_returns_mapping(self):
        """The server should have the possibility to split header lines into a dictionary."""
        lines = [
            'Host: example.com',
            'Upgrade: websocket',
            'Connection: Upgrade',
            'Invalid header',
        ]
        headers = BaseServer._convert_headers_to_dict(lines)

        self.assertEqual({
            'Host': 'example.com',
            'Upgrade': 'websocket',
            'Connection': 'Upgrade',
        }, headers)

    async def test_handle_request_incomplete_read_returns_none(self):
        """The server should have the possibility to return None when
        the client disconnects early.
        """
        class _FakeIncompleteReader:
            async def readuntil(self, _separator):
                raise asyncio.IncompleteReadError(partial=b'', expected=4)

        result = await self.server._handle_request(_FakeIncompleteReader(), self.writer)

        self.assertIsNone(result)
        self.assertTrue(self.writer.closed)
        self.assertTrue(self.writer.wait_closed_called)

    async def test_handle_request_non_get_returns_405(self):
        """The server should have the possibility to reject non-GET methods with 405."""
        request = (
            b'POST /submit HTTP/1.1\r\n'
            b'Host: example.com\r\n'
            b'\r\n'
        )
        with (
            patch.object(self.reader, 'readuntil', return_value=request),
            patch.object(self.server, 'send_http_error') as mock_send_http_error,
        ):
            await self.server._handle_request(self.reader, self.writer)

        self.assertTrue(self.writer.closed)
        mock_send_http_error.assert_awaited_once_with(self.writer, 405, 'Method Not Allowed')

    async def test_handle_request_plain_get_returns_426(self):
        """The server should have the possibility to request websocket upgrade
        for plain GET requests.
        """
        request = (
            b'GET /plain HTTP/1.1\r\n'
            b'Host: example.com\r\n'
            b'\r\n'
        )
        with (
            patch.object(self.reader, 'readuntil', return_value=request),
            patch.object(self.server, 'send_http_error') as mock_send_http_error,
        ):
            await self.server._handle_request(self.reader, self.writer)

        self.assertTrue(self.writer.closed)
        mock_send_http_error.assert_awaited_once_with(
            self.writer, 426, 'Upgrade Required',
        )

    async def test_handle_request_websocket_calls_handler(self):
        """The server should have the possibility to delegate websocket upgrades to
        handle_websocket.
        """
        request = (
            b'GET /ws HTTP/1.1\r\n'
            b'Host: example.com\r\n'
            b'Upgrade: websocket\r\n'
            b'Connection: Upgrade\r\n'
            b'\r\n'
        )
        with (
            patch.object(self.reader, 'readuntil', return_value=request),
            patch.object(
                self.server, '_handle_websocket_request', AsyncMock(),
            ) as mock_handle_websocket_request,
        ):
            await self.server._handle_request(self.reader, self.writer)

        mock_handle_websocket_request.assert_called_once()
        args, _ = mock_handle_websocket_request.call_args
        self.assertEqual(args[3], '/ws')
        self.assertEqual(args[2]['Upgrade'], 'websocket')

    async def test_handle_websocket_custom_handler_used(self):
        """The server should have the possibility to instantiate custom websocket handlers."""
        handler_instance = AsyncMock()
        handler_class = Mock(return_value=handler_instance)
        headers = {'Upgrade': 'websocket'}

        with patch.object(self.server, 'handlers', {'/ws': handler_class}):
            await self.server._handle_websocket_request(self.reader, self.writer, headers, '/ws')

        handler_class.assert_called_once_with(headers, self.reader, self.writer, self.server)
        handler_instance.get.assert_awaited_once()

    async def test_handle_websocket_default_handler_used(self):
        """The server should have the possibility to use the default websocket handler when
        no custom handler exists.
        """
        headers = {'Upgrade': 'websocket'}
        handler_instance = AsyncMock()
        with patch(
            'kate.core.server.websocket.WebSocketHandler',
            return_value=handler_instance,
        ) as mock_default_websocket_handler:
            await self.server._handle_websocket_request(self.reader, self.writer, headers, '/other')

        mock_default_websocket_handler.assert_called_once_with(
            headers, self.reader, self.writer, self.server,
        )
        handler_instance.get.assert_awaited_once()

    async def test_send_http_error_writes_and_closes(self):
        """The server should have the possibility to write an error response and
        close the writer.
        """
        await self.server.send_http_error(self.writer, 400, 'Bad Request')

        self.assertTrue(self.writer.closed)
        self.assertTrue(self.writer.wait_closed_called)

    async def test_send_response_writes_and_drains(self):
        """The server should have the possibility to write response bytes and drain the writer."""
        response = Response('payload')
        with (
            patch.object(self.writer, 'write', return_value=None) as mock_write,
            patch.object(self.writer, 'drain', return_value=None) as mock_drain,
        ):
            await self.server.send_response(self.writer, response)

        mock_write.assert_called_once_with(response.to_bytes())
        mock_drain.assert_awaited_once()

    async def test_start_creates_async_server(self):
        """The server should have the possibility to create and run an asyncio server."""
        server_instance_mock = AsyncMock()
        server_instance_mock.__aenter__.return_value = server_instance_mock
        server_instance_mock.__aexit__.return_value = None

        asyncio_server_mock = AsyncMock(return_value=server_instance_mock)
        with patch('kate.core.server.asyncio.start_server', asyncio_server_mock):
            await self.server.start()

        asyncio_server_mock.assert_awaited_once_with(
            self.server._handle_request,
            self.server._host,
            self.server._port,
            ssl=self.server._ssl_context,
        )
        server_instance_mock.__aenter__.assert_awaited_once()
        server_instance_mock.__aexit__.assert_awaited_once()
        server_instance_mock.serve_forever.assert_awaited_once()

    def test_tls_initializes_ssl_context(self):
        """The server should have the possibility to create SSL context when certificate and
        key are provided.
        """
        context_mock = Mock()
        ssl_cls = Mock(return_value=context_mock)

        with (
            patch('kate.core.server.ssl.SSLContext', ssl_cls),
            patch('kate.core.server.ssl.PROTOCOL_TLS_SERVER', 1),
        ):
            server = BaseServer(ssl_cert=Path('cert.pem'), ssl_key=Path('key.pem'))

        ssl_cls.assert_called_once_with(1)
        context_mock.load_cert_chain.assert_called_once_with(
            certfile='cert.pem',
            keyfile='key.pem',
        )
        self.assertIsNotNone(server._ssl_context)

    def test_tls_skips_without_cert_and_key(self):
        """The server should have the possibility to leave SSL context unset when
        certificate or key is missing.
        """
        server = BaseServer()
        self.assertIsNone(server._ssl_context)
