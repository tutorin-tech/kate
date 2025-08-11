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

"""HTTP utility code shared by clients and servers.

This module also defines the `HTTPServerRequest` class which is exposed
via `tornado.web.RequestHandler.request`.
"""

import calendar
import collections.abc
import copy
import datetime
import email.utils
from functools import lru_cache
from http.client import responses
import re
import time
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from kate.server.escape import native_str, parse_qs_bytes, to_unicode


# responses is unused in this file, but we re-export it to other files.
# Reference it so pyflakes doesn't complain.
responses

import typing
from typing import (
    Tuple,
    Iterable,
    List,
    Iterator,
    Dict,
    Union,
    Optional,
    Awaitable,
)

if typing.TYPE_CHECKING:
    from typing import Deque  # noqa: F401
    from asyncio import Future  # noqa: F401
    import unittest  # noqa: F401

    # This can be done unconditionally in the base class of HTTPHeaders
    # after we drop support for Python 3.8.
    StrMutableMapping = collections.abc.MutableMapping[str, str]
else:
    StrMutableMapping = collections.abc.MutableMapping

# To be used with str.strip() and related methods.
HTTP_WHITESPACE = " \t"

# Roughly the inverse of RequestHandler._VALID_HEADER_CHARS, but permits
# chars greater than \xFF (which may appear after decoding utf8).
_FORBIDDEN_HEADER_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


class _ABNF:
    """Class that holds a subset of ABNF rules from RFC 9110 and friends.

    Class attributes are re.Pattern objects, with the same name as in the RFC
    (with hyphens changed to underscores). Currently contains only the subset
    we use (which is why this class is not public). Unfortunately the fields
    cannot be alphabetized as they are in the RFCs because of dependencies.
    """

    # RFC 3986 (URI)
    # The URI hostname ABNF is both complex (including detailed vaildation of IPv4 and IPv6
    # literals) and not strict enough (a lot of punctuation is allowed by the ABNF even though
    # it is not allowed by DNS). We simplify it by allowing square brackets and colons in any
    # position, not only for their use in IPv6 literals.
    uri_unreserved = re.compile(r"[A-Za-z0-9\-._~]")
    uri_sub_delims = re.compile(r"[!$&'()*+,;=]")
    uri_pct_encoded = re.compile(r"%[0-9A-Fa-f]{2}")
    uri_host = re.compile(
        rf"(?:[\[\]:]|{uri_unreserved.pattern}|{uri_sub_delims.pattern}|{uri_pct_encoded.pattern})*"
    )
    uri_port = re.compile(r"[0-9]*")

    # RFC 5234 (ABNF)
    VCHAR = re.compile(r"[\x21-\x7E]")

    # RFC 9110 (HTTP Semantics)
    obs_text = re.compile(r"[\x80-\xFF]")
    field_vchar = re.compile(rf"(?:{VCHAR.pattern}|{obs_text.pattern})")
    # Not exactly from the RFC to simplify and combine field-content and field-value.
    field_value = re.compile(
        rf"|"
        rf"{field_vchar.pattern}|"
        rf"{field_vchar.pattern}(?:{field_vchar.pattern}| |\t)*{field_vchar.pattern}"
    )
    tchar = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]")
    token = re.compile(rf"{tchar.pattern}+")
    field_name = token
    method = token
    host = re.compile(rf"(?:{uri_host.pattern})(?::{uri_port.pattern})?")

    # RFC 9112 (HTTP/1.1)
    HTTP_version = re.compile(r"HTTP/[0-9]\.[0-9]")
    reason_phrase = re.compile(rf"(?:[\t ]|{VCHAR.pattern}|{obs_text.pattern})+")
    # request_target delegates to the URI RFC 3986, which is complex and may be
    # too restrictive (for example, the WHATWG version of the URL spec allows non-ASCII
    # characters). Instead, we allow everything but control chars and whitespace.
    request_target = re.compile(rf"{field_vchar.pattern}+")
    request_line = re.compile(
        rf"({method.pattern}) ({request_target.pattern}) ({HTTP_version.pattern})"
    )
    status_code = re.compile(r"[0-9]{3}")
    status_line = re.compile(
        rf"({HTTP_version.pattern}) ({status_code.pattern}) ({reason_phrase.pattern})?"
    )


@lru_cache(1000)
def _normalize_header(name: str) -> str:
    """Map a header name to Http-Header-Case.

    >>> _normalize_header("coNtent-TYPE")
    'Content-Type'
    """
    return "-".join([w.capitalize() for w in name.split("-")])


class HTTPHeaders(StrMutableMapping):
    """A dictionary that maintains ``Http-Header-Case`` for all keys.

    Supports multiple values per key via a pair of new methods,
    `add()` and `get_list()`.  The regular dictionary interface
    returns a single value per key, with multiple values joined by a
    comma.

    >>> h = HTTPHeaders({"content-type": "text/html"})
    >>> list(h.keys())
    ['Content-Type']
    >>> h["Content-Type"]
    'text/html'

    >>> h.add("Set-Cookie", "A=B")
    >>> h.add("Set-Cookie", "C=D")
    >>> h["set-cookie"]
    'A=B,C=D'
    >>> h.get_list("set-cookie")
    ['A=B', 'C=D']

    >>> for (k,v) in sorted(h.get_all()):
    ...    print('%s: %s' % (k,v))
    ...
    Content-Type: text/html
    Set-Cookie: A=B
    Set-Cookie: C=D
    """

    def __init__(self, *args: typing.Any, **kwargs: str) -> None:  # noqa: F811
        self._dict = {}  # type: typing.Dict[str, str]
        self._as_list = {}  # type: typing.Dict[str, typing.List[str]]
        self._last_key = None  # type: Optional[str]
        if len(args) == 1 and len(kwargs) == 0 and isinstance(args[0], HTTPHeaders):
            # Copy constructor
            for k, v in args[0].get_all():
                self.add(k, v)
        else:
            # Dict-style initialization
            self.update(*args, **kwargs)

    # new public methods

    def add(self, name: str, value: str, *, _chars_are_bytes: bool = True) -> None:
        """Adds a new value for the given key."""
        if not _ABNF.field_name.fullmatch(name):
            raise HTTPInputError("Invalid header name %r" % name)
        if _chars_are_bytes:
            if not _ABNF.field_value.fullmatch(to_unicode(value)):
                # TODO: the fact we still support bytes here (contrary to type annotations)
                # and still test for it should probably be changed.
                raise HTTPInputError("Invalid header value %r" % value)
        else:
            if _FORBIDDEN_HEADER_CHARS_RE.search(value):
                raise HTTPInputError("Invalid header value %r" % value)
        norm_name = _normalize_header(name)
        self._last_key = norm_name
        if norm_name in self:
            self._dict[norm_name] = (
                native_str(self[norm_name]) + "," + native_str(value)
            )
            self._as_list[norm_name].append(value)
        else:
            self[norm_name] = value

    def get_list(self, name: str) -> List[str]:
        """Returns all values for the given header as a list."""
        norm_name = _normalize_header(name)
        return self._as_list.get(norm_name, [])

    def get_all(self) -> Iterable[Tuple[str, str]]:
        """Returns an iterable of all (name, value) pairs.

        If a header has multiple values, multiple pairs will be
        returned with the same name.
        """
        for name, values in self._as_list.items():
            for value in values:
                yield (name, value)

    def parse_line(self, line: str, *, _chars_are_bytes: bool = True) -> None:
        r"""Updates the dictionary with a single header line.

        >>> h = HTTPHeaders()
        >>> h.parse_line("Content-Type: text/html")
        >>> h.get('content-type')
        'text/html'
        >>> h.parse_line("Content-Length: 42\r\n")
        >>> h.get('content-type')
        'text/html'

        .. versionchanged:: 6.5
            Now supports lines with or without the trailing CRLF, making it possible
            to pass lines from AsyncHTTPClient's header_callback directly to this method.

        .. deprecated:: 6.5
           In Tornado 7.0, certain deprecated features of HTTP will become errors.
           Specifically, line folding and the use of LF (with CR) as a line separator
           will be removed.
        """
        if m := re.search(r"\r?\n$", line):
            # RFC 9112 section 2.2: a recipient MAY recognize a single LF as a line
            # terminator and ignore any preceding CR.
            # TODO(7.0): Remove this support for LF-only line endings.
            line = line[: m.start()]
        if not line:
            # Empty line, or the final CRLF of a header block.
            return
        if line[0] in HTTP_WHITESPACE:
            # continuation of a multi-line header
            # TODO(7.0): Remove support for line folding.
            if self._last_key is None:
                raise HTTPInputError("first header line cannot start with whitespace")
            new_part = " " + line.strip(HTTP_WHITESPACE)
            if _chars_are_bytes:
                if not _ABNF.field_value.fullmatch(new_part[1:]):
                    raise HTTPInputError("Invalid header continuation %r" % new_part)
            else:
                if _FORBIDDEN_HEADER_CHARS_RE.search(new_part):
                    raise HTTPInputError("Invalid header value %r" % new_part)
            self._as_list[self._last_key][-1] += new_part
            self._dict[self._last_key] += new_part
        else:
            try:
                name, value = line.split(":", 1)
            except ValueError:
                raise HTTPInputError("no colon in header line")
            self.add(
                name, value.strip(HTTP_WHITESPACE), _chars_are_bytes=_chars_are_bytes
            )

    @classmethod
    def parse(cls, headers: str, *, _chars_are_bytes: bool = True) -> "HTTPHeaders":
        """Returns a dictionary from HTTP header text.

        >>> h = HTTPHeaders.parse("Content-Type: text/html\\r\\nContent-Length: 42\\r\\n")
        >>> sorted(h.items())
        [('Content-Length', '42'), ('Content-Type', 'text/html')]

        .. versionchanged:: 5.1

           Raises `HTTPInputError` on malformed headers instead of a
           mix of `KeyError`, and `ValueError`.

        """
        # _chars_are_bytes is a hack. This method is used in two places, HTTP headers (in which
        # non-ascii characters are to be interpreted as latin-1) and multipart/form-data (in which
        # they are to be interpreted as utf-8). For historical reasons, this method handled this by
        # expecting both callers to decode the headers to strings before parsing them. This wasn't a
        # problem until we started doing stricter validation of the characters allowed in HTTP
        # headers (using ABNF rules defined in terms of byte values), which inadvertently started
        # disallowing non-latin1 characters in multipart/form-data filenames.
        #
        # This method should have accepted bytes and a desired encoding, but this change is being
        # introduced in a patch release that shouldn't change the API. Instead, the _chars_are_bytes
        # flag decides whether to use HTTP-style ABNF validation (treating the string as bytes
        # smuggled through the latin1 encoding) or to accept any non-control unicode characters
        # as required by multipart/form-data. This method will change to accept bytes in a future
        # release.
        h = cls()

        start = 0
        while True:
            lf = headers.find("\n", start)
            if lf == -1:
                h.parse_line(headers[start:], _chars_are_bytes=_chars_are_bytes)
                break
            line = headers[start : lf + 1]
            start = lf + 1
            h.parse_line(line, _chars_are_bytes=_chars_are_bytes)
        return h

    # MutableMapping abstract method implementations.

    def __setitem__(self, name: str, value: str) -> None:
        norm_name = _normalize_header(name)
        self._dict[norm_name] = value
        self._as_list[norm_name] = [value]

    def __getitem__(self, name: str) -> str:
        return self._dict[_normalize_header(name)]

    def __delitem__(self, name: str) -> None:
        norm_name = _normalize_header(name)
        del self._dict[norm_name]
        del self._as_list[norm_name]

    def __len__(self) -> int:
        return len(self._dict)

    def __iter__(self) -> Iterator[typing.Any]:
        return iter(self._dict)

    def copy(self) -> "HTTPHeaders":
        # defined in dict but not in MutableMapping.
        return HTTPHeaders(self)

    # Use our overridden copy method for the copy.copy module.
    # This makes shallow copies one level deeper, but preserves
    # the appearance that HTTPHeaders is a single container.
    __copy__ = copy

    def __str__(self) -> str:
        lines = []
        for name, value in self.get_all():
            lines.append(f"{name}: {value}\n")
        return "".join(lines)

    __unicode__ = __str__


class HTTPServerRequest:
    """A single HTTP request.

    All attributes are type `str` unless otherwise noted.

    .. attribute:: method

       HTTP request method, e.g. "GET" or "POST"

    .. attribute:: uri

       The requested uri.

    .. attribute:: path

       The path portion of `uri`

    .. attribute:: query

       The query portion of `uri`

    .. attribute:: version

       HTTP version specified in request, e.g. "HTTP/1.1"

    .. attribute:: headers

       `.HTTPHeaders` dictionary-like object for request headers.  Acts like
       a case-insensitive dictionary with additional methods for repeated
       headers.

    .. attribute:: body

       Request body, if present, as a byte string.

    .. attribute:: remote_ip

       Client's IP address as a string.  If ``HTTPServer.xheaders`` is set,
       will pass along the real IP address provided by a load balancer
       in the ``X-Real-Ip`` or ``X-Forwarded-For`` header.

    .. versionchanged:: 3.1
       The list format of ``X-Forwarded-For`` is now supported.

    .. attribute:: protocol

       The protocol used, either "http" or "https".  If ``HTTPServer.xheaders``
       is set, will pass along the protocol used by a load balancer if
       reported via an ``X-Scheme`` header.

    .. attribute:: host

       The requested hostname, usually taken from the ``Host`` header.

    .. attribute:: arguments

       GET/POST arguments are available in the arguments property, which
       maps arguments names to lists of values (to support multiple values
       for individual names). Names are of type `str`, while arguments
       are byte strings.  Note that this is different from
       `.RequestHandler.get_argument`, which returns argument values as
       unicode strings.

    .. attribute:: query_arguments

       Same format as ``arguments``, but contains only arguments extracted
       from the query string.

       .. versionadded:: 3.2

    .. attribute:: body_arguments

       Same format as ``arguments``, but contains only arguments extracted
       from the request body.

       .. versionadded:: 3.2

    .. attribute:: files

       File uploads are available in the files property, which maps file
       names to lists of `.HTTPFile`.

    .. attribute:: connection

       An HTTP request is attached to a single HTTP connection, which can
       be accessed through the "connection" attribute. Since connections
       are typically kept open in HTTP/1.1, multiple requests can be handled
       sequentially on a single connection.

    .. versionchanged:: 4.0
       Moved from ``tornado.httpserver.HTTPRequest``.
    """

    path = None  # type: str
    query = None  # type: str

    # HACK: Used for stream_request_body
    _body_future = None  # type: Future[None]

    def __init__(
        self,
        method: Optional[str] = None,
        uri: Optional[str] = None,
        version: str = "HTTP/1.0",
        headers: Optional[HTTPHeaders] = None,
        body: Optional[bytes] = None,
        # host: Optional[str] = None,
        connection: Optional["HTTPConnection"] = None,
        start_line: Optional["RequestStartLine"] = None,
        server_connection: Optional[object] = None,
    ) -> None:
        if start_line is not None:
            method, uri, version = start_line
        self.method = method
        self.uri = uri
        self.version = version
        self.headers = headers or HTTPHeaders()
        self.body = body or b""

        # set remote IP and protocol
        context = getattr(connection, "context", None)
        self.remote_ip = getattr(context, "remote_ip", None)
        self.protocol = getattr(context, "protocol", "http")

        try:
            self.host = self.headers["Host"]
        except KeyError:
            if version == "HTTP/1.0":
                # HTTP/1.0 does not require the Host header.
                self.host = "127.0.0.1"
            else:
                raise HTTPInputError("Missing Host header")
        if not _ABNF.host.fullmatch(self.host):
            print(_ABNF.host.pattern)
            raise HTTPInputError("Invalid Host header: %r" % self.host)
        if "," in self.host:
            # https://www.rfc-editor.org/rfc/rfc9112.html#name-request-target
            # Server MUST respond with 400 Bad Request if multiple
            # Host headers are present.
            #
            # We test for the presence of a comma instead of the number of
            # headers received because a proxy may have converted
            # multiple headers into a single comma-separated value
            # (per RFC 9110 section 5.3).
            #
            # This is technically a departure from the RFC since the ABNF
            # does not forbid commas in the host header. However, since
            # commas are not allowed in DNS names, it is appropriate to
            # disallow them. (The same argument could be made for other special
            # characters, but commas are the most problematic since they could
            # be used to exploit differences between proxies when multiple headers
            # are supplied).
            raise HTTPInputError("Multiple host headers not allowed: %r" % self.host)
        self.host_name = split_host_and_port(self.host.lower())[0]
        self.connection = connection
        self.server_connection = server_connection
        self._start_time = time.time()
        self._finish_time = None

        if uri is not None:
            self.path, sep, self.query = uri.partition("?")
        self.arguments = parse_qs_bytes(self.query, keep_blank_values=True)
        self.query_arguments = copy.deepcopy(self.arguments)
        self.body_arguments = {}  # type: Dict[str, List[bytes]]

    def request_time(self) -> float:
        """Returns the amount of time it took for this request to execute."""
        if self._finish_time is None:
            return time.time() - self._start_time
        else:
            return self._finish_time - self._start_time

    def __repr__(self) -> str:
        attrs = ("protocol", "host", "method", "uri", "version", "remote_ip")
        args = ", ".join([f"{n}={getattr(self, n)!r}" for n in attrs])
        return f"{self.__class__.__name__}({args})"


class HTTPInputError(Exception):
    """Exception class for malformed HTTP requests or responses
    from remote sources.

    .. versionadded:: 4.0
    """

    pass


class HTTPOutputError(Exception):
    """Exception class for errors in HTTP output.

    .. versionadded:: 4.0
    """

    pass


class HTTPServerConnectionDelegate:
    """Implement this interface to handle requests from `.HTTPServer`.

    .. versionadded:: 4.0
    """

    def start_request(
        self, server_conn: object, request_conn: "HTTPConnection"
    ) -> "HTTPMessageDelegate":
        """This method is called by the server when a new request has started.

        :arg server_conn: is an opaque object representing the long-lived
            (e.g. tcp-level) connection.
        :arg request_conn: is a `.HTTPConnection` object for a single
            request/response exchange.

        This method should return a `.HTTPMessageDelegate`.
        """
        raise NotImplementedError()

    def on_close(self, server_conn: object) -> None:
        """This method is called when a connection has been closed.

        :arg server_conn: is a server connection that has previously been
            passed to ``start_request``.
        """
        pass


class HTTPMessageDelegate:
    """Implement this interface to handle an HTTP request or response.

    .. versionadded:: 4.0
    """

    # TODO: genericize this class to avoid exposing the Union.
    def headers_received(
        self,
        start_line: Union["RequestStartLine", "ResponseStartLine"],
        headers: HTTPHeaders,
    ) -> Optional[Awaitable[None]]:
        """Called when the HTTP headers have been received and parsed.

        :arg start_line: a `.RequestStartLine` or `.ResponseStartLine`
            depending on whether this is a client or server message.
        :arg headers: a `.HTTPHeaders` instance.

        Some `.HTTPConnection` methods can only be called during
        ``headers_received``.

        May return a `.Future`; if it does the body will not be read
        until it is done.
        """
        pass

    def data_received(self, chunk: bytes) -> Optional[Awaitable[None]]:
        """Called when a chunk of data has been received.

        May return a `.Future` for flow control.
        """
        pass

    def finish(self) -> None:
        """Called after the last chunk of data has been received."""
        pass

    def on_connection_close(self) -> None:
        """Called if the connection is closed without finishing the request.

        If ``headers_received`` is called, either ``finish`` or
        ``on_connection_close`` will be called, but not both.
        """
        pass


class HTTPConnection:
    """Applications use this interface to write their responses.

    .. versionadded:: 4.0
    """

    def write_headers(
        self,
        start_line: Union["RequestStartLine", "ResponseStartLine"],
        headers: HTTPHeaders,
        chunk: Optional[bytes] = None,
    ) -> "Future[None]":
        """Write an HTTP header block.

        :arg start_line: a `.RequestStartLine` or `.ResponseStartLine`.
        :arg headers: a `.HTTPHeaders` instance.
        :arg chunk: the first (optional) chunk of data.  This is an optimization
            so that small responses can be written in the same call as their
            headers.

        The ``version`` field of ``start_line`` is ignored.

        Returns a future for flow control.

        .. versionchanged:: 6.0

           The ``callback`` argument was removed.
        """
        raise NotImplementedError()

    def write(self, chunk: bytes) -> "Future[None]":
        """Writes a chunk of body data.

        Returns a future for flow control.

        .. versionchanged:: 6.0

           The ``callback`` argument was removed.
        """
        raise NotImplementedError()

    def finish(self) -> None:
        """Indicates that the last body data has been written."""
        raise NotImplementedError()


def format_timestamp(
    ts: Union[int, float, tuple, time.struct_time, datetime.datetime],
) -> str:
    """Formats a timestamp in the format used by HTTP.

    The argument may be a numeric timestamp as returned by `time.time`,
    a time tuple as returned by `time.gmtime`, or a `datetime.datetime`
    object. Naive `datetime.datetime` objects are assumed to represent
    UTC; aware objects are converted to UTC before formatting.

    >>> format_timestamp(1359312200)
    'Sun, 27 Jan 2013 18:43:20 GMT'
    """
    if isinstance(ts, (int, float)):
        time_num = ts
    elif isinstance(ts, (tuple, time.struct_time)):
        time_num = calendar.timegm(ts)
    elif isinstance(ts, datetime.datetime):
        time_num = calendar.timegm(ts.utctimetuple())
    else:
        raise TypeError("unknown timestamp type: %r" % ts)
    return email.utils.formatdate(time_num, usegmt=True)


class RequestStartLine(typing.NamedTuple):
    method: str
    path: str
    version: str


def parse_request_start_line(line: str) -> RequestStartLine:
    """Returns a (method, path, version) tuple for an HTTP 1.x request line.

    The response is a `typing.NamedTuple`.

    >>> parse_request_start_line("GET /foo HTTP/1.1")
    RequestStartLine(method='GET', path='/foo', version='HTTP/1.1')
    """
    match = _ABNF.request_line.fullmatch(line)
    if not match:
        # https://tools.ietf.org/html/rfc7230#section-3.1.1
        # invalid request-line SHOULD respond with a 400 (Bad Request)
        raise HTTPInputError("Malformed HTTP request line")
    r = RequestStartLine(match.group(1), match.group(2), match.group(3))
    if not r.version.startswith("HTTP/1"):
        # HTTP/2 and above doesn't use parse_request_start_line.
        # This could be folded into the regex but we don't want to deviate
        # from the ABNF in the RFCs.
        raise HTTPInputError("Unexpected HTTP version %r" % r.version)
    return r


class ResponseStartLine(typing.NamedTuple):
    version: str
    code: int
    reason: str

_netloc_re = re.compile(r"^(.+):(\d+)$")


def split_host_and_port(netloc: str) -> Tuple[str, Optional[int]]:
    """Returns ``(host, port)`` tuple from ``netloc``.

    Returned ``port`` will be ``None`` if not present.

    .. versionadded:: 4.1
    """
    match = _netloc_re.match(netloc)
    if match:
        host = match.group(1)
        port = int(match.group(2))  # type: Optional[int]
    else:
        host = netloc
        port = None
    return (host, port)
