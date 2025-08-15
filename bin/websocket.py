import asyncio
import logging
from pathlib import Path
import struct

HOST = 'localhost'
PORT = 8080
STATIC_DIR = Path(__file__).parent / 'static'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WebSocketHandler:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.client_closed = False

    async def open(self):
        pass

    async def on_message(self, message: str):
        pass

    async def on_close(self):
        pass

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
            await self.on_close()

    def _encode_length(self, length):
        if length <= 125:
            return struct.pack("!B", length)
        elif length <= 65535:
            return struct.pack("!BH", 126, length)
        else:
            return struct.pack("!BQ", 127, length)
