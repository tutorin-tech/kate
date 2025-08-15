
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
        """Create the file descriptor.

        Returns:
            Created file descriptor.

        """
        pid, fd = pty.fork()
        if pid == 0:
            if os.getuid() == 0:
                cmd = ['/bin/login']
            else:
                # The prompt has to end with a newline character.
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
            return os.execvpe(cmd[0], cmd, env)  # noqa: S606

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
        """Destroy the file descriptor."""
        try:
            os.kill(TerminalWebSocketHandler.clients[fd]['pid'], signal.SIGHUP)
            os.close(fd)
        except OSError:
            pass

        del TerminalWebSocketHandler.clients[fd]

    def open(self):
        """Handle a new WebSocket connection."""
        def callback(*_args, **_kwargs):
            buf = os.read(self._fd, 65536)
            client = TerminalWebSocketHandler.clients[self._fd]
            html = client['terminal'].generate_html(buf)
            client['client'].write_message(html)

        self._fd = self._create()
        self._loop.add_reader(self._fd, callback)

    def on_message(self, data):
        """Handle incoming messages on the WebSocket."""
        try:
            os.write(self._fd, data.encode('utf8'))
        except OSError:
            self._destroy(self._fd)

    def on_close(self):
        """Handle the case when the WebSocket is closed."""
        # self._loop.remove_handler(self._fd)
        self._destroy(self._fd)
