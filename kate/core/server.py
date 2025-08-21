"""The module contains a base implementation of the server."""

import asyncio
import contextlib
import logging
import ssl
from http import HTTPStatus
from pathlib import Path

from kate.core import websocket
from kate.core.httputil import parse_request_start_line

LOGGER = logging.getLogger(__name__)


class Response:
    """The class represents a HTTP response wrapper that encapsulates status code,
    headers, and body data.
    """

    def __init__(self, body: bytes | str = b'', status: int = 200, headers: dict | None = None):
        """Initialize a Response object."""
        self.status = status
        self.reason = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else 'OK'
        self.headers = {'Connection': 'close'}
        if headers:
            self.headers.update(headers)

        self.body = body.encode() if isinstance(body, str) else (body or b'')

    def clear_header(self, name: str):
        """Remove a header from the response headers dict."""
        if name in self.headers:
            del self.headers[name]

    def set_header(self, name: str, value: str):
        """Set or update an HTTP response header."""
        self.headers[name] = value

    def set_status(self, status: int, reason: str | None = None):
        """Update HTTP response status code and reason phrase."""
        self.status = status
        self.reason = reason or (
            HTTPStatus(status).phrase
            if status in HTTPStatus._value2member_map_
            else ''
        )

    def to_bytes(self) -> bytes:
        """Serialize response to HTTP/1.1 wire format bytes."""
        headers = {
            **self.headers,
            'Content-Length': str(len(self.body)),
        }
        head = [f'HTTP/1.1 {self.status} {self.reason}'] + [f'{k}: {v}' for k, v in headers.items()]
        return ('\r\n'.join(head) + '\r\n\r\n').encode() + self.body


class BaseServer:
    """The class represents a base implementation of the server."""

    handlers = None

    def __init__(
        self,
        host: str = '127.0.0.1',
        port: int = 8888,
        ssl_cert: Path | None = None,
        ssl_key: Path | None = None,
    ):
        """Initialize a BaseServer object."""
        self._host = host
        self._port = port
        self._ssl_context = None

        if ssl_cert and ssl_key:
            self._ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self._ssl_context.load_cert_chain(certfile=str(ssl_cert), keyfile=str(ssl_key))

    #
    # Private
    #

    @staticmethod
    def _convert_headers_to_dict(lines):
        """Parse HTTP header lines into key-value dictionary."""
        headers = {}
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip()] = value.strip()

        return headers

    async def _handle_request(self, reader, writer):
        """Parse and route HTTP/WebSocket requests from client connection."""
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
            return await self._handle_websocket_request(reader, writer, headers, path)

        return await self.send_http_error(writer, 426, 'Upgrade Required')

    async def _handle_websocket_request(self, reader, writer, headers, path):
        """Route WebSocket upgrade request to appropriate handler instance."""
        args = (headers, reader, writer, self)
        if self.handlers is not None and self.handlers.get(path):
            handler = self.handlers[path](*args)
        else:
            handler = websocket.WebSocketHandler(*args)

        await handler.get()

    #
    # Public
    #

    async def send_http_error(
        self,
        writer,
        code: int,
        message: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        """Send HTTP error response and close connection."""
        response = Response(
            HTTPStatus(code).phrase if message is None else message,
            status=code,
            headers={'Content-Type': 'text/plain; charset=utf-8'} if headers is None else headers,
        )
        await self.send_response(writer, response)

        writer.close()
        with contextlib.suppress(ConnectionResetError):
            await writer.wait_closed()

    @staticmethod
    async def send_response(writer: asyncio.StreamWriter, response: Response):
        """Transmit HTTP response over asyncio writer stream."""
        writer.write(response.to_bytes())
        await writer.drain()

    async def start(self):
        """Start asyncio TCP server and begin accepting connections."""
        socket_server = await asyncio.start_server(
            self._handle_request, self._host, self._port, ssl=self._ssl_context,
        )
        async with socket_server:
            LOGGER.info('Serving on http://%s:%s', self._host, self._port)
            await socket_server.serve_forever()
