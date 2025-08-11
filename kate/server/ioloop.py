#
# Copyright 2009 Facebook
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

"""An I/O event loop for non-blocking sockets.

In Tornado 6.0, `.IOLoop` is a wrapper around the `asyncio` event loop, with a
slightly different interface. The `.IOLoop` interface is now provided primarily
for backwards compatibility; new code should generally use the `asyncio` event
loop interface directly. The `IOLoop.current` class method provides the
`IOLoop` instance corresponding to the running `asyncio` event loop.

"""

import asyncio
import datetime
import functools
import logging
import numbers
import time
import warnings

from kate.server.concurrent import (
    Future,
    is_future,
    future_add_done_callback,
)
from kate.server.util import Configurable, import_object

import typing
from typing import Union, Any, Type, Optional, Callable, TypeVar, Tuple

if typing.TYPE_CHECKING:
    from typing import Dict, List, Set, TypedDict  # noqa: F401

    from typing_extensions import Protocol
else:
    Protocol = object

LOGGER = logging.getLogger(__name__)


class _Selectable(Protocol):
    def fileno(self) -> int:
        pass

    def close(self) -> None:
        pass


_T = TypeVar("_T")
_S = TypeVar("_S", bound=_Selectable)


class IOLoop(Configurable):
    """An I/O event loop.

    As of Tornado 6.0, `IOLoop` is a wrapper around the `asyncio` event loop.

    Example usage for a simple TCP server:

    .. testcode::

        import asyncio
        import errno
        import functools
        import socket

        import tornado
        from kate.server.iostream import IOStream

        async def handle_connection(connection, address):
            stream = IOStream(connection)
            message = await stream.read_until_close()
            print("message from client:", message.decode().strip())

        def connection_ready(sock, fd, events):
            while True:
                try:
                    connection, address = sock.accept()
                except BlockingIOError:
                    return
                connection.setblocking(0)
                io_loop = tornado.ioloop.IOLoop.current()
                io_loop.spawn_callback(handle_connection, connection, address)

        async def main():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setblocking(0)
            sock.bind(("", 8888))
            sock.listen(128)

            io_loop = tornado.ioloop.IOLoop.current()
            callback = functools.partial(connection_ready, sock)
            io_loop.add_handler(sock.fileno(), callback, io_loop.READ)
            await asyncio.Event().wait()

        if __name__ == "__main__":
            asyncio.run(main())

    Most applications should not attempt to construct an `IOLoop` directly,
    and instead initialize the `asyncio` event loop and use `IOLoop.current()`.
    In some cases, such as in test frameworks when initializing an `IOLoop`
    to be run in a secondary thread, it may be appropriate to construct
    an `IOLoop` with ``IOLoop(make_current=False)``.

    In general, an `IOLoop` cannot survive a fork or be shared across processes
    in any way. When multiple processes are being used, each process should
    create its own `IOLoop`, which also implies that any objects which depend on
    the `IOLoop` (such as `.AsyncHTTPClient`) must also be created in the child
    processes. As a guideline, anything that starts processes (including the
    `tornado.process` and `multiprocessing` modules) should do so as early as
    possible, ideally the first thing the application does after loading its
    configuration, and *before* any calls to `.IOLoop.start` or `asyncio.run`.

    .. versionchanged:: 4.2
       Added the ``make_current`` keyword argument to the `IOLoop`
       constructor.

    .. versionchanged:: 5.0

       Uses the `asyncio` event loop by default. The ``IOLoop.configure`` method
       cannot be used on Python 3 except to redundantly specify the `asyncio`
       event loop.

    .. versionchanged:: 6.3
       ``make_current=True`` is now the default when creating an IOLoop -
       previously the default was to make the event loop current if there wasn't
       already a current one.
    """

    # These constants were originally based on constants from the epoll module.
    NONE = 0
    READ = 0x001
    WRITE = 0x004
    ERROR = 0x018

    # In Python 3, _ioloop_for_asyncio maps from asyncio loops to IOLoops.
    _ioloop_for_asyncio = dict()  # type: Dict[asyncio.AbstractEventLoop, IOLoop]

    # Maintain a set of all pending tasks to follow the warning in the docs
    # of asyncio.create_tasks:
    # https://docs.python.org/3.11/library/asyncio-task.html#asyncio.create_task
    # This ensures that all pending tasks have a strong reference so they
    # will not be garbage collected before they are finished.
    # (Thus avoiding "task was destroyed but it is pending" warnings)
    # An analogous change has been proposed in cpython for 3.13:
    # https://github.com/python/cpython/issues/91887
    # If that change is accepted, this can eventually be removed.
    # If it is not, we will consider the rationale and may remove this.
    _pending_tasks = set()  # type: Set[Future]

    @staticmethod
    def current(instance: bool = True) -> Optional["IOLoop"]:  # noqa: F811
        """Returns the current thread's `IOLoop`.

        If an `IOLoop` is currently running or has been marked as
        current by `make_current`, returns that instance.  If there is
        no current `IOLoop` and ``instance`` is true, creates one.

        .. versionchanged:: 4.1
           Added ``instance`` argument to control the fallback to
           `IOLoop.instance()`.
        .. versionchanged:: 5.0
           On Python 3, control of the current `IOLoop` is delegated
           to `asyncio`, with this and other methods as pass-through accessors.
           The ``instance`` argument now controls whether an `IOLoop`
           is created automatically when there is none, instead of
           whether we fall back to `IOLoop.instance()` (which is now
           an alias for this method). ``instance=False`` is deprecated,
           since even if we do not create an `IOLoop`, this method
           may initialize the asyncio loop.

        .. deprecated:: 6.2
           It is deprecated to call ``IOLoop.current()`` when no `asyncio`
           event loop is running.
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            if not instance:
                return None
            # Create a new asyncio event loop for this thread.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            return IOLoop._ioloop_for_asyncio[loop]
        except KeyError:
            if instance:
                from kate.server.platform.asyncio import AsyncIOMainLoop

                current = AsyncIOMainLoop()  # type: Optional[IOLoop]
            else:
                current = None
        return current

    def _make_current(self) -> None:
        # The asyncio event loops override this method.
        raise NotImplementedError()

    @classmethod
    def configurable_base(cls) -> Type[Configurable]:
        return IOLoop

    @classmethod
    def configurable_default(cls) -> Type[Configurable]:
        from kate.server.platform.asyncio import AsyncIOLoop

        return AsyncIOLoop

    def initialize(self, make_current: bool = True) -> None:
        if make_current:
            self._make_current()

    def close(self, all_fds: bool = False) -> None:
        """Closes the `IOLoop`, freeing any resources used.

        If ``all_fds`` is true, all file descriptors registered on the
        IOLoop will be closed (not just the ones created by the
        `IOLoop` itself).

        Many applications will only use a single `IOLoop` that runs for the
        entire lifetime of the process.  In that case closing the `IOLoop`
        is not necessary since everything will be cleaned up when the
        process exits.  `IOLoop.close` is provided mainly for scenarios
        such as unit tests, which create and destroy a large number of
        ``IOLoops``.

        An `IOLoop` must be completely stopped before it can be closed.  This
        means that `IOLoop.stop()` must be called *and* `IOLoop.start()` must
        be allowed to return before attempting to call `IOLoop.close()`.
        Therefore the call to `close` will usually appear just after
        the call to `start` rather than near the call to `stop`.

        .. versionchanged:: 3.1
           If the `IOLoop` implementation supports non-integer objects
           for "file descriptors", those objects will have their
           ``close`` method when ``all_fds`` is true.
        """
        raise NotImplementedError()

    def add_handler(  # noqa: F811
        self, fd: Union[int, _Selectable], handler: Callable[..., None], events: int
    ) -> None:
        """Registers the given handler to receive the given events for ``fd``.

        The ``fd`` argument may either be an integer file descriptor or
        a file-like object with a ``fileno()`` and ``close()`` method.

        The ``events`` argument is a bitwise or of the constants
        ``IOLoop.READ``, ``IOLoop.WRITE``, and ``IOLoop.ERROR``.

        When an event occurs, ``handler(fd, events)`` will be run.

        .. versionchanged:: 4.0
           Added the ability to pass file-like objects in addition to
           raw file descriptors.
        """
        raise NotImplementedError()

    def update_handler(self, fd: Union[int, _Selectable], events: int) -> None:
        """Changes the events we listen for ``fd``.

        .. versionchanged:: 4.0
           Added the ability to pass file-like objects in addition to
           raw file descriptors.
        """
        raise NotImplementedError()

    def remove_handler(self, fd: Union[int, _Selectable]) -> None:
        """Stop listening for events on ``fd``.

        .. versionchanged:: 4.0
           Added the ability to pass file-like objects in addition to
           raw file descriptors.
        """
        raise NotImplementedError()

    def start(self) -> None:
        """Starts the I/O loop.

        The loop will run until one of the callbacks calls `stop()`, which
        will make the loop stop after the current event iteration completes.
        """
        raise NotImplementedError()

    def stop(self) -> None:
        """Stop the I/O loop.

        If the event loop is not currently running, the next call to `start()`
        will return immediately.

        Note that even after `stop` has been called, the `IOLoop` is not
        completely stopped until `IOLoop.start` has also returned.
        Some work that was scheduled before the call to `stop` may still
        be run before the `IOLoop` shuts down.
        """
        raise NotImplementedError()

    def time(self) -> float:
        """Returns the current time according to the `IOLoop`'s clock.

        The return value is a floating-point number relative to an
        unspecified time in the past.

        Historically, the IOLoop could be customized to use e.g.
        `time.monotonic` instead of `time.time`, but this is not
        currently supported and so this method is equivalent to
        `time.time`.

        """
        return time.time()

    def add_timeout(
        self,
        deadline: Union[float, datetime.timedelta],
        callback: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> object:
        """Runs the ``callback`` at the time ``deadline`` from the I/O loop.

        Returns an opaque handle that may be passed to
        `remove_timeout` to cancel.

        ``deadline`` may be a number denoting a time (on the same
        scale as `IOLoop.time`, normally `time.time`), or a
        `datetime.timedelta` object for a deadline relative to the
        current time.  Since Tornado 4.0, `call_later` is a more
        convenient alternative for the relative case since it does not
        require a timedelta object.

        Note that it is not safe to call `add_timeout` from other threads.
        Instead, you must use `add_callback` to transfer control to the
        `IOLoop`'s thread, and then call `add_timeout` from there.

        Subclasses of IOLoop must implement either `add_timeout` or
        `call_at`; the default implementations of each will call
        the other.  `call_at` is usually easier to implement, but
        subclasses that wish to maintain compatibility with Tornado
        versions prior to 4.0 must use `add_timeout` instead.

        .. versionchanged:: 4.0
           Now passes through ``*args`` and ``**kwargs`` to the callback.
        """
        if isinstance(deadline, numbers.Real):
            return self.call_at(deadline, callback, *args, **kwargs)
        elif isinstance(deadline, datetime.timedelta):
            return self.call_at(
                self.time() + deadline.total_seconds(), callback, *args, **kwargs
            )
        else:
            raise TypeError("Unsupported deadline %r" % deadline)

    def remove_timeout(self, timeout: object) -> None:
        """Cancels a pending timeout.

        The argument is a handle as returned by `add_timeout`.  It is
        safe to call `remove_timeout` even if the callback has already
        been run.
        """
        raise NotImplementedError()

    def add_callback(self, callback: Callable, *args: Any, **kwargs: Any) -> None:
        """Calls the given callback on the next I/O loop iteration.

        It is safe to call this method from any thread at any time,
        except from a signal handler.  Note that this is the **only**
        method in `IOLoop` that makes this thread-safety guarantee; all
        other interaction with the `IOLoop` must be done from that
        `IOLoop`'s thread.  `add_callback()` may be used to transfer
        control from other threads to the `IOLoop`'s thread.
        """
        raise NotImplementedError()

    def add_callback_from_signal(
        self, callback: Callable, *args: Any, **kwargs: Any
    ) -> None:
        """Calls the given callback on the next I/O loop iteration.

        Intended to be afe for use from a Python signal handler; should not be
        used otherwise.

        .. deprecated:: 6.4
           Use ``asyncio.AbstractEventLoop.add_signal_handler`` instead.
           This method is suspected to have been broken since Tornado 5.0 and
           will be removed in version 7.0.
        """
        raise NotImplementedError()

    def add_future(
        self,
        future: "Union[Future[_T], concurrent.futures.Future[_T]]",
        callback: Callable[["Future[_T]"], None],
    ) -> None:
        """Schedules a callback on the ``IOLoop`` when the given
        `.Future` is finished.

        The callback is invoked with one argument, the
        `.Future`.

        This method only accepts `.Future` objects and not other
        awaitables (unlike most of Tornado where the two are
        interchangeable).
        """
        if isinstance(future, Future):
            # Note that we specifically do not want the inline behavior of
            # tornado.concurrent.future_add_done_callback. We always want
            # this callback scheduled on the next IOLoop iteration (which
            # asyncio.Future always does).
            #
            # Wrap the callback in self._run_callback so we control
            # the error logging (i.e. it goes to tornado.log.app_log
            # instead of asyncio's log).
            future.add_done_callback(
                lambda f: self._run_callback(functools.partial(callback, f))
            )
        else:
            assert is_future(future)
            # For concurrent futures, we use self.add_callback, so
            # it's fine if future_add_done_callback inlines that call.
            future_add_done_callback(future, lambda f: self.add_callback(callback, f))

    def _run_callback(self, callback: Callable[[], Any]) -> None:
        """Runs a callback with error handling.

        .. versionchanged:: 6.0

           CancelledErrors are no longer logged.
        """
        try:
            ret = callback()
            if ret is not None:
                from kate.server import gen

                # Functions that return Futures typically swallow all
                # exceptions and store them in the Future.  If a Future
                # makes it out to the IOLoop, ensure its exception (if any)
                # gets logged too.
                try:
                    ret = gen.convert_yielded(ret)
                except gen.BadYieldError:
                    # It's not unusual for add_callback to be used with
                    # methods returning a non-None and non-yieldable
                    # result, which should just be ignored.
                    pass
                else:
                    self.add_future(ret, self._discard_future_result)
        except asyncio.CancelledError:
            pass
        except Exception:
            LOGGER.error("Exception in callback %r", callback, exc_info=True)

    def _discard_future_result(self, future: Future) -> None:
        """Avoid unhandled-exception warnings from spawned coroutines."""
        future.result()

    def split_fd(
        self, fd: Union[int, _Selectable]
    ) -> Tuple[int, Union[int, _Selectable]]:
        # """Returns an (fd, obj) pair from an ``fd`` parameter.

        # We accept both raw file descriptors and file-like objects as
        # input to `add_handler` and related methods.  When a file-like
        # object is passed, we must retain the object itself so we can
        # close it correctly when the `IOLoop` shuts down, but the
        # poller interfaces favor file descriptors (they will accept
        # file-like objects and call ``fileno()`` for you, but they
        # always return the descriptor itself).

        # This method is provided for use by `IOLoop` subclasses and should
        # not generally be used by application code.

        # .. versionadded:: 4.0
        # """
        if isinstance(fd, int):
            return fd, fd
        return fd.fileno(), fd

    def _register_task(self, f: Future) -> None:
        self._pending_tasks.add(f)

    def _unregister_task(self, f: Future) -> None:
        self._pending_tasks.discard(f)
