"""The module contains a base implementation of the server."""

import asyncio
import contextlib
import logging
import mimetypes
import ssl
from http import HTTPStatus
from pathlib import Path

from kate.core import websocket
from kate.core.httputil import parse_request_start_line

LOGGER = logging.getLogger(__name__)


class Response:
    """The class implements a wrap for HTTP-response."""

    def __init__(self, body: bytes | str = b'', status: int = 200, headers: dict | None = None):
        """Initialize a Response object."""
        self.status = status
        self.reason = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else 'OK'
        self.headers = {'Connection': 'close'}
        if headers:
            self.headers.update(headers)

        self.body = body.encode() if isinstance(body, str) else (body or b'')

    def set_status(self, status: int, reason: str | None = None):
        """Set the status code for our response."""
        self.status = status
        self.reason = reason or (
            HTTPStatus(status).phrase
            if status in HTTPStatus._value2member_map_
            else ''
        )

    def set_header(self, name: str, value: str):
        """Set the given response header name and value."""
        self.headers[name] = value

    def clear_header(self, name: str):
        """Clear an outgoing header."""
        if name in self.headers:
            del self.headers[name]

    def to_bytes(self) -> bytes:
        """Return a response object in a bytes format."""
        headers = {
            **self.headers,
            'Content-Length': str(len(self.body)),
        }
        head = [f'HTTP/1.1 {self.status} {self.reason}'] + [f'{k}: {v}' for k, v in headers.items()]
        return ('\r\n'.join(head) + '\r\n\r\n').encode() + self.body


class BaseServer:
    """The class represents a base implementation of the server."""

    handlers = None
    server = None

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
    async def send_response(writer: asyncio.StreamWriter, response: Response):
        """Send a response in a bytes format."""
        writer.write(response.to_bytes())
        await writer.drain()

    async def send_http_error(self, writer, code: int, message: str | None = None):
        """Send HTTP error."""
        response = Response(
            message or HTTPStatus(code).phrase,
            status=code,
            headers={'Content-Type': 'text/plain; charset=utf-8'},
        )
        await self.send_response(writer, response)

        writer.close()
        with contextlib.suppress(ConnectionResetError):
            await writer.wait_closed()

    async def handle_request(self, reader, writer):
        """Handle a request."""
        try:
            request = await reader.readuntil(b'\r\n\r\n')
        except asyncio.IncompleteReadError:
            writer.close()
            with contextlib.suppress(ConnectionResetError):
                await writer.wait_closed()

            return None

        header_lines = request.decode(errors='replace').split('\r\n')
        request_line = parse_request_start_line(header_lines[0])
        method = request_line.method.upper()

        if method != 'GET':
            return await self.send_http_error(writer, 405, 'Method Not Allowed')

        path = request_line.path
        headers = self._convert_headers_to_dict(header_lines[1:])
        if headers.get('Upgrade') and 'upgrade' in headers.get('Connection', '').lower():
            return await self.handle_websocket(reader, writer, headers, path)

        return await self.handle_static_file_request(path, writer)

    async def handle_static_file_request(self, path: str, writer: asyncio.StreamWriter):
        """Handle a request for static files."""
        path = (
            '/index.html'
            if path == '/' else
            path.replace('/static', '')  # rework
        )
        file_path = self._static_path / path.lstrip('/')

        if not file_path.exists():
            return await self.send_http_error(writer, 404, 'File not found')

        mime_type, _ = mimetypes.guess_type(file_path.name)
        mime_type = mime_type or 'application/octet-stream'
        content = file_path.read_bytes()

        response = Response(content, status=200, headers={'Content-Type': mime_type})
        return await self.send_response(writer, response)

    async def handle_websocket(self, reader, writer, headers, path):
        """Choose websocket handler according to the `handlers` attribute."""
        args = (headers, reader, writer, self)
        if self.handlers is not None and self.handlers.get(path):
            handler = self.handlers[path](*args)
        else:
            handler = websocket.WebSocketHandler(*args)

        await handler.get()

    async def start(self):
        """Start a socket server."""
        server = await asyncio.start_server(
            self.handle_request, self._host, self._port, ssl=self._ssl_context,
        )
        self.server = server

        LOGGER.info('Serving on https://%s:%s', self._host, self._port)
        async with self.server:
            await self.server.serve_forever()
