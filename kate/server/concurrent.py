#
# Copyright 2012 Facebook
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
"""Utilities for working with ``Future`` objects.

Tornado previously provided its own ``Future`` class, but now uses
`asyncio.Future`. This module contains utility functions for working
with `asyncio.Future` in a way that is backwards-compatible with
Tornado's old ``Future`` implementation.

While this module is an important part of Tornado's internal
implementation, applications rarely need to interact with it
directly.

"""

import asyncio
from concurrent import futures
import logging
import types

import typing
from typing import Any, Callable, Optional, Tuple, Union

_T = typing.TypeVar("_T")

Future = asyncio.Future

FUTURES = (futures.Future, Future)

LOGGER = logging.getLogger(__name__)


def is_future(x: Any) -> bool:
    return isinstance(x, FUTURES)


def chain_future(
    a: Union["Future[_T]", "futures.Future[_T]"],
    b: Union["Future[_T]", "futures.Future[_T]"],
) -> None:
    """Chain two futures together so that when one completes, so does the other.

    The result (success or failure) of ``a`` will be copied to ``b``, unless
    ``b`` has already been completed or cancelled by the time ``a`` finishes.

    .. versionchanged:: 5.0

       Now accepts both Tornado/asyncio `Future` objects and
       `concurrent.futures.Future`.

    """

    def copy(a: "Future[_T]") -> None:
        if b.done():
            return
        if hasattr(a, "exc_info") and a.exc_info() is not None:  # type: ignore
            future_set_exc_info(b, a.exc_info())  # type: ignore
        else:
            a_exc = a.exception()
            if a_exc is not None:
                b.set_exception(a_exc)
            else:
                b.set_result(a.result())

    if isinstance(a, Future):
        future_add_done_callback(a, copy)
    else:
        # concurrent.futures.Future
        from kate.server.ioloop import IOLoop

        IOLoop.current().add_future(a, copy)


def future_set_result_unless_cancelled(
    future: "Union[futures.Future[_T], Future[_T]]", value: _T
) -> None:
    """Set the given ``value`` as the `Future`'s result, if not cancelled.

    Avoids ``asyncio.InvalidStateError`` when calling ``set_result()`` on
    a cancelled `asyncio.Future`.

    .. versionadded:: 5.0
    """
    if not future.cancelled():
        future.set_result(value)


def future_set_exception_unless_cancelled(
    future: "Union[futures.Future[_T], Future[_T]]", exc: BaseException
) -> None:
    """Set the given ``exc`` as the `Future`'s exception.

    If the Future is already canceled, logs the exception instead. If
    this logging is not desired, the caller should explicitly check
    the state of the Future and call ``Future.set_exception`` instead of
    this wrapper.

    Avoids ``asyncio.InvalidStateError`` when calling ``set_exception()`` on
    a cancelled `asyncio.Future`.

    .. versionadded:: 6.0

    """
    if not future.cancelled():
        future.set_exception(exc)
    else:
        LOGGER.error("Exception after Future was cancelled", exc_info=exc)


def future_set_exc_info(
    future: "Union[futures.Future[_T], Future[_T]]",
    exc_info: Tuple[
        Optional[type], Optional[BaseException], Optional[types.TracebackType]
    ],
) -> None:
    """Set the given ``exc_info`` as the `Future`'s exception.

    Understands both `asyncio.Future` and the extensions in older
    versions of Tornado to enable better tracebacks on Python 2.

    .. versionadded:: 5.0

    .. versionchanged:: 6.0

       If the future is already cancelled, this function is a no-op.
       (previously ``asyncio.InvalidStateError`` would be raised)

    """
    if exc_info[1] is None:
        raise Exception("future_set_exc_info called with no exception")
    future_set_exception_unless_cancelled(future, exc_info[1])


def future_add_done_callback(  # noqa: F811
    future: "Union[futures.Future[_T], Future[_T]]", callback: Callable[..., None]
) -> None:
    """Arrange to call ``callback`` when ``future`` is complete.

    ``callback`` is invoked with one argument, the ``future``.

    If ``future`` is already done, ``callback`` is invoked immediately.
    This may differ from the behavior of ``Future.add_done_callback``,
    which makes no such guarantee.

    .. versionadded:: 5.0
    """
    if future.done():
        callback(future)
    else:
        future.add_done_callback(callback)
