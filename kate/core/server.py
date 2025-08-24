"""The module contains a base implementation of the server."""

import asyncio
import logging
import mimetypes
import ssl
from pathlib import Path

from kate.core.websocket import WebSocketHandler
from kate.core.websocket.httputil import parse_request_start_line

LOGGER = logging.getLogger(__name__)


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


class BaseServer:
    """The class represents a base implementation of the server."""

    handlers = None

    def __init__(
        self,
        host: str = '127.0.0.1',
        port: int = 8888,
        static_path: 'Path | None' = None,
        ssl_cert: 'Path | None' = None,
        ssl_key: 'Path | None' = None,
    ):
        """Initialize a server object."""
        self._host = host
        self._port = port
        self._static_path = static_path or Path.cwd() / 'frontend' / 'dist'
        self._ssl_context = None

        if ssl_cert and ssl_key:
            self._ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self._ssl_context.load_cert_chain(certfile=str(ssl_cert), keyfile=str(ssl_key))

    @staticmethod
    def _convert_headers_to_dict(lines):
        """Return header as a dictionary."""
        headers = {}
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip()] = value.strip()

        return headers

    @staticmethod
    async def _send_http_error(writer, code, message):
        message = message.encode()
        response = (
            f'HTTP/1.1 {code} {message}\r\n'
            f'Content-Type: text/plain\r\n'
            f'Content-Length: {len(message)}\r\n'
            f'\r\n'
        ).encode() + message

        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def handle_request(self, reader, writer):
        """Handle a request."""
        try:
            request = await reader.readuntil(b'\r\n\r\n')
        except asyncio.IncompleteReadError:
            return writer.close()

        header_lines = request.decode().split('\r\n')
        request_line = parse_request_start_line(header_lines[0])
        if request_line.method != 'GET':
            return await self._send_http_error(
                writer,
                405,
                'Method Not Allowed',
            )

        headers = self._convert_headers_to_dict(header_lines)
        if headers.get('Upgrade', ''):
            return await self.handle_websocket(reader, writer, headers, request_line.path)

        return await self.handle_static_file_request(request_line.path, writer)

    async def handle_static_file_request(self, path: str, writer: asyncio.StreamWriter):
        """Handle a request for static files."""
        path = (
            '/index.html'
            if path == '/' else
            path.replace('/static', '')  # rework
        )
        file_path = self._static_path / path.lstrip('/')

        if file_path.exists():
            mime_type, _ = mimetypes.guess_type(file_path.name)
            mime_type = mime_type or 'application/octet-stream'

            content = file_path.read_bytes()
            headers = (
                f'HTTP/1.1 200 OK\r\n'
                f'Content-Type: {mime_type}\r\n'
                f'Content-Length: {len(content)}\r\n'
                f'\r\n'
            )
            response = headers.encode('utf-8') + content
        else:
            response = b'HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\n\r\nFile not found'

        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def handle_websocket(self, reader, writer, headers, path):
        """Choose websocket handler according to the `handlers` attribute."""
        if self.handlers is not None and self.handlers.get(path):
            handler = self.handlers[path](headers, reader, writer)
        else:
            handler = WebSocketHandler(headers, reader, writer)

        await handler.get()

    async def start(self):
        """Start a socket server."""
        server = await asyncio.start_server(
            self.handle_request, self._host, self._port, ssl=self._ssl_context,
        )

        LOGGER.info('Serving on https://%s:%s', self._host, self._port)
        async with server:
            await server.serve_forever()
