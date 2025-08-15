import asyncio
import hashlib
import base64
import os
import mimetypes
import struct

HOST = '127.0.0.1'
PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MAGIC_STRING = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

async def handle_client(reader, writer):
    request = await reader.read(2048)
    headers = request.decode(errors='ignore').split("\r\n")
    if not headers:
        writer.close()
        await writer.wait_closed()
        return

    request_line = headers[0]
    print(f"Request: {request_line}")
    method, path, _ = request_line.split()

    # WebSocket handshake
    if path == "/termsocket" and 'Upgrade: websocket' in "\r\n".join(headers):
        await handle_websocket(reader, writer, headers)
        return

    # Serve static files
    if method != 'GET':
        response = "HTTP/1.1 405 Method Not Allowed\r\n\r\n"
        writer.write(response.encode())
        await writer.drain()
        writer.close()
        return

    if path == '/':
        path = '/home/cusdeb-1/Projects/kate/frontend/dist/index.html'
    elif path.startswith('/static'):
        a = path.replace('static', 'dist')
        path = f'/home/cusdeb-1/Projects/kate/frontend/{a}'
        print(path)

    # if not os.path.isfile(file_path):
    #     response = "HTTP/1.1 404 Not Found\r\n\r\nFile not found"
    #     writer.write(response.encode())
    #     await writer.drain()
    #     writer.close()
    #     return

    mime_type, _ = mimetypes.guess_type(path)
    mime_type = mime_type or 'application/octet-stream'

    with open(path, 'rb') as f:
        content = f.read()

    headers = [
        "HTTP/1.1 200 OK",
        f"Content-Type: {mime_type}",
        f"Content-Length: {len(content)}",
        "Connection: close",
        "\r\n"
    ]
    writer.write("\r\n".join(headers).encode() + content)
    await writer.drain()
    writer.close()
    await writer.wait_closed()

async def handle_websocket(reader, writer, headers):
    # Парсинг WebSocket заголовков
    key = None
    for line in headers:
        if line.lower().startswith('sec-websocket-key'):
            key = line.split(":")[1].strip()
            break

    if not key:
        writer.close()
        await writer.wait_closed()
        return

    accept_key = base64.b64encode(
        hashlib.sha1((key + MAGIC_STRING).encode()).digest()
    ).decode()

    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key}\r\n"
        "\r\n"
    )
    writer.write(response.encode())
    await writer.drain()

    print("🧩 WebSocket connection established")

    try:
        while not reader.at_eof():
            data = await read_ws_message(reader)
            # data = await read_ws_message(reader)
            if data is None:
                break
            print(f"📨 Received: {data}")
            await send_ws_message(writer, f"Echo: {data}")
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        writer.close()
        await writer.wait_closed()
        print("❌ WebSocket connection closed")

async def read_ws_message(reader):
    # Простейшая реализация чтения только текстовых сообщений
    header = await reader.readexactly(2)
    fin = header[0] & 0b10000000
    opcode = header[0] & 0b00001111
    masked = header[1] & 0b10000000
    length = header[1] & 0b01111111

    if length == 126:
        length = struct.unpack(">H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", await reader.readexactly(8))[0]

    if masked:
        mask = await reader.readexactly(4)
        encrypted = await reader.readexactly(length)
        decoded = bytes(b ^ mask[i % 4] for i, b in enumerate(encrypted))
    else:
        decoded = await reader.readexactly(length)

    if opcode == 8:
        return None  # close frame

    return decoded.decode()

async def send_ws_message(writer, message):
    encoded = message.encode()
    header = bytearray([0b10000001])  # FIN + text frame
    length = len(encoded)
    if length <= 125:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header += struct.pack(">H", length)
    else:
        header.append(127)
        header += struct.pack(">Q", length)
    writer.write(header + encoded)
    await writer.drain()

async def main():
    server = await asyncio.start_server(handle_client, HOST, PORT)
    addr = server.sockets[0].getsockname()
    print(f"📡 Serving on http://{addr[0]}:{addr[1]}")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
