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

"""Miscellaneous network utility code."""

import errno
import os
import sys
import socket

from kate.server.ioloop import IOLoop
from kate.server.util import errno_from_exception

from typing import List, Callable, Any, Optional

# ThreadedResolver runs getaddrinfo on a thread. If the hostname is unicode,
# getaddrinfo attempts to import encodings.idna. If this is done at
# module-import time, the import lock is already held by the main thread,
# leading to deadlock. Avoid it by caching the idna encoder on the main
# thread now.
"foo".encode("idna")

# For undiagnosed reasons, 'latin1' codec may also need to be preloaded.
"foo".encode("latin1")

# Default backlog used when calling sock.listen()
_DEFAULT_BACKLOG = 128


def bind_sockets(
    port: int,
    address: Optional[str] = None,
    family: socket.AddressFamily = socket.AF_UNSPEC,
    backlog: int = _DEFAULT_BACKLOG,
    flags: Optional[int] = None,
    reuse_port: bool = False,
) -> List[socket.socket]:
    """Creates listening sockets bound to the given port and address.

    Returns a list of socket objects (multiple sockets are returned if
    the given address maps to multiple IP addresses, which is most common
    for mixed IPv4 and IPv6 use).

    Address may be either an IP address or hostname.  If it's a hostname,
    the server will listen on all IP addresses associated with the
    name.  Address may be an empty string or None to listen on all
    available interfaces.  Family may be set to either `socket.AF_INET`
    or `socket.AF_INET6` to restrict to IPv4 or IPv6 addresses, otherwise
    both will be used if available.

    The ``backlog`` argument has the same meaning as for
    `socket.listen() <socket.socket.listen>`.

    ``flags`` is a bitmask of AI_* flags to `~socket.getaddrinfo`, like
    ``socket.AI_PASSIVE | socket.AI_NUMERICHOST``.

    ``reuse_port`` option sets ``SO_REUSEPORT`` option for every socket
    in the list. If your platform doesn't support this option ValueError will
    be raised.
    """
    if reuse_port and not hasattr(socket, "SO_REUSEPORT"):
        raise ValueError("the platform doesn't support SO_REUSEPORT")

    sockets = []
    if address == "":
        address = None
    if not socket.has_ipv6 and family == socket.AF_UNSPEC:
        # Python can be compiled with --disable-ipv6, which causes
        # operations on AF_INET6 sockets to fail, but does not
        # automatically exclude those results from getaddrinfo
        # results.
        # http://bugs.python.org/issue16208
        family = socket.AF_INET
    if flags is None:
        flags = socket.AI_PASSIVE
    bound_port = None
    unique_addresses = set()  # type: set
    for res in sorted(
        socket.getaddrinfo(address, port, family, socket.SOCK_STREAM, 0, flags),
        key=lambda x: x[0],
    ):
        if res in unique_addresses:
            continue

        unique_addresses.add(res)

        af, socktype, proto, canonname, sockaddr = res
        if (
            sys.platform == "darwin"
            and address == "localhost"
            and af == socket.AF_INET6
            and sockaddr[3] != 0  # type: ignore
        ):
            # Mac OS X includes a link-local address fe80::1%lo0 in the
            # getaddrinfo results for 'localhost'.  However, the firewall
            # doesn't understand that this is a local address and will
            # prompt for access (often repeatedly, due to an apparent
            # bug in its ability to remember granting access to an
            # application). Skip these addresses.
            continue
        try:
            sock = socket.socket(af, socktype, proto)
        except OSError as e:
            if errno_from_exception(e) == errno.EAFNOSUPPORT:
                continue
            raise
        if os.name != "nt":
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except OSError as e:
                if errno_from_exception(e) != errno.ENOPROTOOPT:
                    # Hurd doesn't support SO_REUSEADDR.
                    raise
        if reuse_port:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        if af == socket.AF_INET6:
            # On linux, ipv6 sockets accept ipv4 too by default,
            # but this makes it impossible to bind to both
            # 0.0.0.0 in ipv4 and :: in ipv6.  On other systems,
            # separate sockets *must* be used to listen for both ipv4
            # and ipv6.  For consistency, always disable ipv4 on our
            # ipv6 sockets and use a separate ipv4 socket when needed.
            #
            # Python 2.x on windows doesn't have IPPROTO_IPV6.
            if hasattr(socket, "IPPROTO_IPV6"):
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)

        # automatic port allocation with port=None
        # should bind on the same port on IPv4 and IPv6
        host, requested_port = sockaddr[:2]
        if requested_port == 0 and bound_port is not None:
            sockaddr = tuple([host, bound_port] + list(sockaddr[2:]))

        sock.setblocking(False)
        try:
            sock.bind(sockaddr)
        except OSError as e:
            if (
                errno_from_exception(e) == errno.EADDRNOTAVAIL
                and address == "localhost"
                and sockaddr[0] == "::1"
            ):
                # On some systems (most notably docker with default
                # configurations), ipv6 is partially disabled:
                # socket.has_ipv6 is true, we can create AF_INET6
                # sockets, and getaddrinfo("localhost", ...,
                # AF_PASSIVE) resolves to ::1, but we get an error
                # when binding.
                #
                # Swallow the error, but only for this specific case.
                # If EADDRNOTAVAIL occurs in other situations, it
                # might be a real problem like a typo in a
                # configuration.
                sock.close()
                continue
            else:
                raise
        bound_port = sock.getsockname()[1]
        sock.listen(backlog)
        sockets.append(sock)
    return sockets


def add_accept_handler(
    sock: socket.socket, callback: Callable[[socket.socket, Any], None]
) -> Callable[[], None]:
    """Adds an `.IOLoop` event handler to accept new connections on ``sock``.

    When a connection is accepted, ``callback(connection, address)`` will
    be run (``connection`` is a socket object, and ``address`` is the
    address of the other end of the connection).  Note that this signature
    is different from the ``callback(fd, events)`` signature used for
    `.IOLoop` handlers.

    A callable is returned which, when called, will remove the `.IOLoop`
    event handler and stop processing further incoming connections.

    .. versionchanged:: 5.0
       The ``io_loop`` argument (deprecated since version 4.1) has been removed.

    .. versionchanged:: 5.0
       A callable is returned (``None`` was returned before).
    """
    io_loop = IOLoop.current()
    removed = [False]

    def accept_handler(fd: socket.socket, events: int) -> None:
        # More connections may come in while we're handling callbacks;
        # to prevent starvation of other tasks we must limit the number
        # of connections we accept at a time.  Ideally we would accept
        # up to the number of connections that were waiting when we
        # entered this method, but this information is not available
        # (and rearranging this method to call accept() as many times
        # as possible before running any callbacks would have adverse
        # effects on load balancing in multiprocess configurations).
        # Instead, we use the (default) listen backlog as a rough
        # heuristic for the number of connections we can reasonably
        # accept at once.
        for i in range(_DEFAULT_BACKLOG):
            if removed[0]:
                # The socket was probably closed
                return
            try:
                connection, address = sock.accept()
            except BlockingIOError:
                # EWOULDBLOCK indicates we have accepted every
                # connection that is available.
                return
            except ConnectionAbortedError:
                # ECONNABORTED indicates that there was a connection
                # but it was closed while still in the accept queue.
                # (observed on FreeBSD).
                continue
            callback(connection, address)

    def remove_handler() -> None:
        io_loop.remove_handler(sock)
        removed[0] = True

    io_loop.add_handler(sock, accept_handler, IOLoop.READ)
    return remove_handler
