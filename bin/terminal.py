
import asyncio
import fcntl
import os
import pty
import signal
import socket  # only for gethostname()
import struct
import sys
import termios

from bin.websocket import WebSocketHandler
from kate.terminal import Terminal


class TerminalWebSocketHandler(WebSocketHandler):

    clients = {}

    def __init__(self, reader, writer):
        super().__init__(reader, writer)
        self._fd = None
        self._loop = asyncio.get_running_loop()

    def _create(self, rows=24, cols=80):
        pid, fd = pty.fork()
        if pid == 0:
            if os.getuid() == 0:
                cmd = ['/bin/login']
            else:
                sys.stdout.write(socket.gethostname() + ' login: \n')
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
        TerminalWebSocketHandler.clients[fd] = {
            'client': self,
            'pid': pid,
            'terminal': Terminal(rows, cols),
        }
        return fd

    @staticmethod
    def _destroy(fd):
        try:
            os.kill(TerminalWebSocketHandler.clients[fd]['pid'], signal.SIGHUP)
            os.close(fd)
        except OSError:
            pass
        del TerminalWebSocketHandler.clients[fd]

    async def open(self):
        self._fd = self._create()

        def reader_callback():
            try:
                buf = os.read(self._fd, 65536)
                client = TerminalWebSocketHandler.clients[self._fd]
                html = client['terminal'].generate_html(buf)
                asyncio.create_task(client['client'].send(html))
            except OSError:
                self._destroy(self._fd)

        self._loop.add_reader(self._fd, reader_callback)

        while True:
            msg = await self.recv()
            if msg is None:
                break
            try:
                os.write(self._fd, msg.encode('utf8'))
            except OSError:
                self._destroy(self._fd)
                break

        await self.close()

    async def on_close(self):
        self._loop.remove_reader(self._fd)
        self._destroy(self._fd)
