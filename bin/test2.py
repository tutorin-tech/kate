import asyncio
import base64
import hashlib
import logging
import mimetypes
import os
from pathlib import Path
import struct
import pty
import fcntl
import signal
import sys
import termios
import socket as pysocket
from kate.terminal import Terminal  # Подразумевается, что он уже есть

HOST = 'localhost'
PORT = 8080
STATIC_DIR = Path(__file__).parent.parent / 'frontend' / 'dist'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebSocketConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.client_closed = False

    async def send(self, message: str):
        if self.client_closed:
            return
        data = message.encode("utf-8")
        frame = b"\x81" + self._encode_length(len(data)) + data
        self.writer.write(frame)
        await self.writer.drain()

    async def recv(self):
        try:
            header = await self.reader.readexactly(2)
        except asyncio.IncompleteReadError:
            self.client_closed = True
            return None

        opcode = header[0] & 0x0F
        if opcode == 0x8:
            self.client_closed = True
            return None

        masked = header[1] & 0x80
        length = header[1] & 0x7F

        if length == 126:
            length = struct.unpack("!H", await self.reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", await self.reader.readexactly(8))[0]

        if masked:
            mask = await self.reader.readexactly(4)
            encoded = await self.reader.readexactly(length)
            decoded = bytes(b ^ mask[i % 4] for i, b in enumerate(encoded))
        else:
            decoded = await self.reader.readexactly(length)

        return decoded.decode("utf-8")

    async def close(self):
        if not self.client_closed:
            self.writer.write(b"\x88\x00")
            await self.writer.drain()
            self.client_closed = True
            self.writer.close()
            await self.writer.wait_closed()

    def _encode_length(self, length):
        if length <= 125:
            return struct.pack("!B", length)
        elif length <= 65535:
            return struct.pack("!BH", 126, length)
        else:
            return struct.pack("!BQ", 127, length)

# === PATCHED: TermSocketHandler-like logic ===

clients = {}

async def terminal_socket_handler(ws: WebSocketConnection):
    loop = asyncio.get_running_loop()

    def _create(rows=24, cols=80):
        pid, fd = pty.fork()
        if pid == 0:
            if os.getuid() == 0:
                cmd = ['/bin/login']
            else:
                sys.stdout.write(pysocket.gethostname() + ' login: \n')
                login = sys.stdin.readline().strip()
                cmd = [
                    'ssh',
                    '-oPreferredAuthentications=keyboard-interactive,password',
                    '-oNoHostAuthenticationForLocalhost=yes',
                    '-oLogLevel=FATAL',
                    '-F/dev/null',
                    '-l', login, 'localhost',
                ]
            env = {
                'COLUMNS': str(cols),
                'LINES': str(rows),
                'PATH': os.environ['PATH'],
                'TERM': 'linux',
            }
            return os.execvpe(cmd[0], cmd, env)

        fcntl.fcntl(fd, fcntl.F_SETFL, os.O_NONBLOCK)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        clients[fd] = {
            'ws': ws,
            'pid': pid,
            'terminal': Terminal(rows, cols),
        }
        return fd

    def _destroy(fd):
        try:
            os.kill(clients[fd]['pid'], signal.SIGHUP)
            os.close(fd)
        except OSError:
            pass
        del clients[fd]

    fd = _create()

    def reader_callback():
        try:
            buf = os.read(fd, 65536)
            client = clients[fd]
            html = client['terminal'].generate_html(buf)
            asyncio.create_task(client['ws'].send(html))
        except OSError:
            _destroy(fd)

    loop.add_reader(fd, reader_callback)

    try:
        while True:
            msg = await ws.recv()
            if msg is None:
                break
            try:
                os.write(fd, msg.encode('utf8'))
            except OSError:
                _destroy(fd)
                break
    finally:
        loop.remove_reader(fd)
        _destroy(fd)
        await ws.close()

# === END PATCH ===

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        request = await reader.readuntil(b"\r\n\r\n")
    except asyncio.IncompleteReadError:
        writer.close()
        return

    headers = request.decode(errors="ignore").split("\r\n")
    request_line = headers[0]
    path = request_line.split()[1]

    if any("upgrade: websocket" in h.lower() for h in headers):
        await handle_websocket(reader, writer, headers, path)
    else:
        await handle_static_file(path, writer)


async def handle_static_file(path: str, writer: asyncio.StreamWriter):
    if path == "/":
        path = "/index.html"

    file_path = STATIC_DIR / path.lstrip("/")
    a = str(file_path).replace('/static', '')
    file_path = Path(a)
    print(path)
    if not file_path.exists():
        response = b"HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\n\r\nFile not found"
        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return

    content = file_path.read_bytes()
    mime_type, _ = mimetypes.guess_type(file_path.name)
    mime_type = mime_type or "application/octet-stream"

    headers = f"HTTP/1.1 200 OK\r\nContent-Type: {mime_type}\r\nContent-Length: {len(content)}\r\n\r\n"
    writer.write(headers.encode("utf-8") + content)
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def handle_websocket(reader, writer, headers, path):
    key = None
    for header in headers:
        if header.lower().startswith("sec-websocket-key"):
            key = header.split(":", 1)[1].strip()
            break

    if not key:
        writer.close()
        await writer.wait_closed()
        return

    accept = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
    ).decode("utf-8")

    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    writer.write(response.encode("utf-8"))
    await writer.drain()

    ws = WebSocketConnection(reader, writer)

    # === PATCHED: dispatch terminal socket ===
    if path == "/termsocket":
        await terminal_socket_handler(ws)
    else:
        try:
            while True:
                msg = await ws.recv()
                if msg is None:
                    break
                logger.info(f"WebSocket received: {msg}")
                await ws.send(f"Echo: {msg}")
        finally:
            await ws.close()


async def main():
    server = await asyncio.start_server(handle_client, HOST, PORT)
    addr = server.sockets[0].getsockname()
    print(f"Serving HTTP and WebSocket on {addr}")
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
