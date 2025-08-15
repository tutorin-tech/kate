import argparse
import asyncio
import logging
import mimetypes
import pathlib
from pathlib import Path

from bin.terminal_websocket import TerminalWebSocketHandler

LOGGER = logging.getLogger(__file__)


class Server:

    _required_websocket_fields = (
        "Host",
        "Sec-WebSocket-Key",
        "Sec-WebSocket-Version",
    )

    def __init__(self, host, port, static_path):
        self._host = host
        self._port = port
        self._static_path = pathlib.Path(static_path)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request = await reader.readuntil(b"\r\n\r\n")
        except asyncio.IncompleteReadError:
            writer.close()
            return

        headers = request.decode(errors="ignore").split("\r\n")
        request_line = headers[0]
        path = request_line.split()[1]

        if any("upgrade: websocket" in h.lower() for h in headers):
            if not all(map(lambda f: headers, self._required_websocket_fields)):
                raise ValueError("Missing/Invalid WebSocket headers")

            await TerminalWebSocketHandler(reader, writer).handle_websocket(headers)
        else:
            await self._handle_static_file(path, writer)

    async def _handle_static_file(self, path: str, writer: asyncio.StreamWriter):
        path = (
            "/index.html"
            if path == "/" else
            path.replace('/static', '')  # TODO (?)
        )
        file_path = self._static_path / path.lstrip("/")

        if file_path.exists():
            mime_type, _ = mimetypes.guess_type(file_path.name)
            mime_type = mime_type or "application/octet-stream"

            content = file_path.read_bytes()
            headers = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: {mime_type}\r\n"
                f"Content-Length: {len(content)}\r\n"
                f"\r\n"
            )
            response = headers.encode("utf-8") + content
        else:
            response = b"HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\n\r\nFile not found"

        await self._write(writer, response)

    @staticmethod
    async def _write(writer, response):
        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def run_server(self):
        """Start a socket server."""
        server = await asyncio.start_server(self._handle_client, self._host, self._port)
        LOGGER.info(' Starting server at http://%s:%s', self._host, self._port)

        async with server:
            await server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--static-path',
        help='the path to static resources',
        default=Path.cwd().parent / Path('frontend/dist'),
    )
    parser.add_argument(
        '--host',
        help='listen on a specific host',
        default='127.0.0.1',
    )
    parser.add_argument(
        '--port',
        help='listen on a specific port',
        default=8888,
    )
    args = parser.parse_args()

    asyncio.run(
        Server(
            host=args.host,
            port=args.port,
            static_path=args.static_path,
        ).run_server(),
    )
