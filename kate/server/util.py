"""Miscellaneous utility functions and classes.

This module is used internally by Tornado.  It is not necessarily expected
that the functions and classes defined here will be useful to other
applications, but they are documented here in case they are.

The one public-facing part of this module is the `Configurable` class
and its `~Configurable.configure` method, which becomes a part of the
interface of its subclasses, including `.AsyncHTTPClient`, `.IOLoop`,
and `.Resolver`.
"""

import array
import asyncio
import re
import typing

from typing import (
    Any,
    Optional,
    Dict,
    Match,
    Callable,
    Type,
)

if typing.TYPE_CHECKING:
    # Additional imports only used in type comments.
    # This lets us make these imports lazy.
    import datetime  # noqa: F401
    from types import TracebackType  # noqa: F401
    from typing import Union  # noqa: F401
    import unittest  # noqa: F401

unicode_type = str
basestring_type = str

# versionchanged:: 6.2
# no longer our own TimeoutError, use standard asyncio class
TimeoutError = asyncio.TimeoutError


def import_object(name: str) -> Any:
    """Imports an object by name."""
    if name.count(".") == 0:
        return __import__(name)

    parts = name.split(".")
    obj = __import__(".".join(parts[:-1]), fromlist=[parts[-1]])
    try:
        return getattr(obj, parts[-1])
    except AttributeError:
        raise ImportError("No module named %s" % parts[-1])


def errno_from_exception(e: BaseException) -> Optional[int]:
    """Provides the errno from an Exception object.

    There are cases that the errno attribute was not set so we pull
    the errno out of the args but if someone instantiates an Exception
    without any args you will get a tuple error. So this function
    abstracts all that behavior to give you a safe way to get the
    errno.
    """

    if hasattr(e, "errno"):
        return e.errno  # type: ignore
    elif e.args:
        return e.args[0]
    else:
        return None


_alphanum = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def _re_unescape_replacement(match: Match[str]) -> str:
    group = match.group(1)
    if group[0] in _alphanum:
        raise ValueError("cannot unescape '\\\\%s'" % group[0])
    return group


_re_unescape_pattern = re.compile(r"\\(.)", re.DOTALL)


def re_unescape(s: str) -> str:
    r"""Unescape a string escaped by `re.escape`.

    May raise ``ValueError`` for regular expressions which could not
    have been produced by `re.escape` (for example, strings containing
    ``\d`` cannot be unescaped).

    .. versionadded:: 4.4
    """
    return _re_unescape_pattern.sub(_re_unescape_replacement, s)


class Configurable:
    """Base class for configurable interfaces.

    A configurable interface is an (abstract) class whose constructor
    acts as a factory function for one of its implementation subclasses.
    The implementation subclass as well as optional keyword arguments to
    its initializer can be set globally at runtime with `configure`.

    By using the constructor as the factory method, the interface
    looks like a normal class, `isinstance` works as usual, etc.  This
    pattern is most useful when the choice of implementation is likely
    to be a global decision (e.g. when `~select.epoll` is available,
    always use it instead of `~select.select`), or when a
    previously-monolithic class has been split into specialized
    subclasses.

    Configurable subclasses must define the class methods
    `configurable_base` and `configurable_default`, and use the instance
    method `initialize` instead of ``__init__``.

    .. versionchanged:: 5.0

       It is now possible for configuration to be specified at
       multiple levels of a class hierarchy.

    """

    # Type annotations on this class are mostly done with comments
    # because they need to refer to Configurable, which isn't defined
    # until after the class definition block. These can use regular
    # annotations when our minimum python version is 3.7.
    #
    # There may be a clever way to use generics here to get more
    # precise types (i.e. for a particular Configurable subclass T,
    # all the types are subclasses of T, not just Configurable).
    __impl_class = None  # type: Optional[Type[Configurable]]
    __impl_kwargs = None  # type: Dict[str, Any]

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        base = cls.configurable_base()
        init_kwargs = {}  # type: Dict[str, Any]
        if cls is base:
            impl = cls.configured_class()
            if base.__impl_kwargs:
                init_kwargs.update(base.__impl_kwargs)
        else:
            impl = cls
        init_kwargs.update(kwargs)
        if impl.configurable_base() is not base:
            # The impl class is itself configurable, so recurse.
            return impl(*args, **init_kwargs)
        instance = super().__new__(impl)
        # initialize vs __init__ chosen for compatibility with AsyncHTTPClient
        # singleton magic.  If we get rid of that we can switch to __init__
        # here too.
        instance.initialize(*args, **init_kwargs)
        return instance

    @classmethod
    def configurable_base(cls):
        # type: () -> Type[Configurable]
        """Returns the base class of a configurable hierarchy.

        This will normally return the class in which it is defined.
        (which is *not* necessarily the same as the ``cls`` classmethod
        parameter).

        """
        raise NotImplementedError()

    @classmethod
    def configurable_default(cls):
        # type: () -> Type[Configurable]
        """Returns the implementation class to be used if none is configured."""
        raise NotImplementedError()

    def _initialize(self) -> None:
        pass

    initialize = _initialize  # type: Callable[..., None]
    """Initialize a `Configurable` subclass instance.

    Configurable classes should use `initialize` instead of ``__init__``.

    .. versionchanged:: 4.2
       Now accepts positional arguments in addition to keyword arguments.
    """

    @classmethod
    def configured_class(cls):
        # type: () -> Type[Configurable]
        """Returns the currently configured class."""
        base = cls.configurable_base()
        # Manually mangle the private name to see whether this base
        # has been configured (and not another base higher in the
        # hierarchy).
        if base.__dict__.get("_Configurable__impl_class") is None:
            base.__impl_class = cls.configurable_default()
        if base.__impl_class is not None:
            return base.__impl_class
        else:
            # Should be impossible, but mypy wants an explicit check.
            raise ValueError("configured class not found")


def _websocket_mask_python(mask: bytes, data: bytes) -> bytes:
    """Websocket masking function.

    `mask` is a `bytes` object of length 4; `data` is a `bytes` object of any length.
    Returns a `bytes` object of the same length as `data` with the mask applied
    as specified in section 5.3 of RFC 6455.

    This pure-python implementation may be replaced by an optimized version when available.
    """
    mask_arr = array.array("B", mask)
    unmasked_arr = array.array("B", data)
    for i in range(len(data)):
        unmasked_arr[i] = unmasked_arr[i] ^ mask_arr[i % 4]
    return unmasked_arr.tobytes()

_websocket_mask = _websocket_mask_python
