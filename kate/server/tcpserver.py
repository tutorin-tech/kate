#
# Copyright 2011 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""A non-blocking, single-threaded TCP server."""

import logging
import socket

from kate.server import gen
from kate.server.ioloop import IOLoop
from kate.server.iostream import IOStream
from kate.server.netutil import (
    bind_sockets,
    add_accept_handler,
    _DEFAULT_BACKLOG,
)

import typing
from typing import Dict, Any, Iterable, Optional

if typing.TYPE_CHECKING:
    from typing import Callable, List  # noqa: F401

LOGGER = logging.getLogger(__name__)


class TCPServer:
    r"""A non-blocking, single-threaded TCP server.

    To use `TCPServer`, define a subclass which overrides the `handle_stream`
    method. For example, a simple echo server could be defined like this::

      from tornado.tcpserver import TCPServer
      from tornado.iostream import StreamClosedError

      class EchoServer(TCPServer):
          async def handle_stream(self, stream, address):
              while True:
                  try:
                      data = await stream.read_until(b"\n") await
                      stream.write(data)
                  except StreamClosedError:
                      break

    To make this server serve SSL traffic, send the ``ssl_options`` keyword
    argument with an `ssl.SSLContext` object. For compatibility with older
    versions of Python ``ssl_options`` may also be a dictionary of keyword
    arguments for the `ssl.SSLContext.wrap_socket` method.::

       ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
       ssl_ctx.load_cert_chain(os.path.join(data_dir, "mydomain.crt"),
                               os.path.join(data_dir, "mydomain.key"))
       TCPServer(ssl_options=ssl_ctx)

    `TCPServer` initialization follows one of three patterns:

    1. `listen`: single-process::

            async def main():
                server = TCPServer()
                server.listen(8888)
                await asyncio.Event().wait()

            asyncio.run(main())

       While this example does not create multiple processes on its own, when
       the ``reuse_port=True`` argument is passed to ``listen()`` you can run
       the program multiple times to create a multi-process service.

    2. `add_sockets`: multi-process::

            sockets = bind_sockets(8888)
            tornado.process.fork_processes(0)
            async def post_fork_main():
                server = TCPServer()
                server.add_sockets(sockets)
                await asyncio.Event().wait()
            asyncio.run(post_fork_main())

       The `add_sockets` interface is more complicated, but it can be used with
       `tornado.process.fork_processes` to run a multi-process service with all
       worker processes forked from a single parent.  `add_sockets` can also be
       used in single-process servers if you want to create your listening
       sockets in some way other than `~tornado.netutil.bind_sockets`.

       Note that when using this pattern, nothing that touches the event loop
       can be run before ``fork_processes``.

    3. `bind`/`start`: simple **deprecated** multi-process::

            server = TCPServer()
            server.bind(8888)
            server.start(0)  # Forks multiple sub-processes
            IOLoop.current().start()

       This pattern is deprecated because it requires interfaces in the
       `asyncio` module that have been deprecated since Python 3.10. Support for
       creating multiple processes in the ``start`` method will be removed in a
       future version of Tornado.

    .. versionadded:: 3.1
       The ``max_buffer_size`` argument.

    .. versionchanged:: 5.0
       The ``io_loop`` argument has been removed.
    """

    def __init__(
        self,
        max_buffer_size: Optional[int] = None,
        read_chunk_size: Optional[int] = None,
    ) -> None:
        self._sockets = {}  # type: Dict[int, socket.socket]
        self._handlers = {}  # type: Dict[int, Callable[[], None]]
        self._pending_sockets = []  # type: List[socket.socket]
        self._started = False
        self._stopped = False
        self.max_buffer_size = max_buffer_size
        self.read_chunk_size = read_chunk_size

    def listen(
        self,
        port: int,
        address: Optional[str] = None,
        family: socket.AddressFamily = socket.AF_UNSPEC,
        backlog: int = _DEFAULT_BACKLOG,
        flags: Optional[int] = None,
        reuse_port: bool = False,
    ) -> None:
        """Starts accepting connections on the given port.

        This method may be called more than once to listen on multiple ports.
        `listen` takes effect immediately; it is not necessary to call
        `TCPServer.start` afterwards.  It is, however, necessary to start the
        event loop if it is not already running.

        All arguments have the same meaning as in
        `tornado.netutil.bind_sockets`.

        .. versionchanged:: 6.2

           Added ``family``, ``backlog``, ``flags``, and ``reuse_port``
           arguments to match `tornado.netutil.bind_sockets`.
        """
        sockets = bind_sockets(
            port,
            address=address,
            family=family,
            backlog=backlog,
            flags=flags,
            reuse_port=reuse_port,
        )
        self.add_sockets(sockets)

    def add_sockets(self, sockets: Iterable[socket.socket]) -> None:
        """Makes this server start accepting connections on the given sockets.

        The ``sockets`` parameter is a list of socket objects such as
        those returned by `~tornado.netutil.bind_sockets`.
        `add_sockets` is typically used in combination with that
        method and `tornado.process.fork_processes` to provide greater
        control over the initialization of a multi-process server.
        """
        for sock in sockets:
            self._sockets[sock.fileno()] = sock
            self._handlers[sock.fileno()] = add_accept_handler(
                sock, self._handle_connection
            )

    def _handle_connection(self, connection: socket.socket, address: Any) -> None:
        try:
            stream = IOStream(
                connection,
                max_buffer_size=self.max_buffer_size,
                read_chunk_size=self.read_chunk_size,
            )

            future = self.handle_stream(stream, address)
            if future is not None:
                IOLoop.current().add_future(
                    gen.convert_yielded(future), lambda f: f.result()
                )
        except Exception:
            LOGGER.error("Error in connection callback", exc_info=True)
