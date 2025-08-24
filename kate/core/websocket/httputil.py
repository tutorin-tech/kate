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

"""HTTP utility code shared by clients and servers."""

import calendar
import collections.abc
import datetime
import email.utils
from functools import lru_cache
from http.client import responses
import re
import time

from tornado.escape import native_str, to_unicode
from tornado.util import ObjectDict


# responses is unused in this file, but we re-export it to other files.
# Reference it so pyflakes doesn't complain.
responses

import typing
from typing import (
    Tuple,
    Iterable,
    List,
    Mapping,
    Iterator,
    Dict,
    Union,
    Optional,
    Generator,
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

native_str = to_unicode


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

    @typing.overload
    def __init__(self, __arg: Mapping[str, List[str]]) -> None:
        pass

    @typing.overload  # noqa: F811
    def __init__(self, __arg: Mapping[str, str]) -> None:
        pass

    @typing.overload  # noqa: F811
    def __init__(self, *args: Tuple[str, str]) -> None:
        pass

    @typing.overload  # noqa: F811
    def __init__(self, **kwargs: str) -> None:
        pass

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


class HTTPInputError(Exception):
    """Exception class for malformed HTTP requests or responses
    from remote sources.

    """

    pass


class HTTPFile(ObjectDict):
    """Represents a file uploaded via a form.

    For backwards compatibility, its instance attributes are also
    accessible as dictionary keys.

    * ``filename``
    * ``body``
    * ``content_type``
    """

    filename: str
    body: bytes
    content_type: str


def _parse_request_range(
    range_header: str,
) -> Optional[Tuple[Optional[int], Optional[int]]]:
    """Parses a Range header.

    Returns either ``None`` or tuple ``(start, end)``.
    Note that while the HTTP headers use inclusive byte positions,
    this method returns indexes suitable for use in slices.

    >>> start, end = _parse_request_range("bytes=1-2")
    >>> start, end
    (1, 3)
    >>> [0, 1, 2, 3, 4][start:end]
    [1, 2]
    >>> _parse_request_range("bytes=6-")
    (6, None)
    >>> _parse_request_range("bytes=-6")
    (-6, None)
    >>> _parse_request_range("bytes=-0")
    (None, 0)
    >>> _parse_request_range("bytes=")
    (None, None)
    >>> _parse_request_range("foo=42")
    >>> _parse_request_range("bytes=1-2,6-10")

    Note: only supports one range (ex, ``bytes=1-2,6-10`` is not allowed).

    See [0] for the details of the range header.

    [0]: http://greenbytes.de/tech/webdav/draft-ietf-httpbis-p5-range-latest.html#byte.ranges
    """
    unit, _, value = range_header.partition("=")
    unit, value = unit.strip(), value.strip()
    if unit != "bytes":
        return None
    start_b, _, end_b = value.partition("-")
    try:
        start = _int_or_none(start_b)
        end = _int_or_none(end_b)
    except ValueError:
        return None
    if end is not None:
        if start is None:
            if end != 0:
                start = -end
                end = None
        else:
            end += 1
    return (start, end)


def _get_content_range(start: Optional[int], end: Optional[int], total: int) -> str:
    """Returns a suitable Content-Range header:

    >>> print(_get_content_range(None, 1, 4))
    bytes 0-0/4
    >>> print(_get_content_range(1, 3, 4))
    bytes 1-2/4
    >>> print(_get_content_range(None, None, 4))
    bytes 0-3/4
    """
    start = start or 0
    end = (end or total) - 1
    return f"bytes {start}-{end}/{total}"


def _int_or_none(val: str) -> Optional[int]:
    val = val.strip()
    if val == "":
        return None
    return int(val)


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


# _parseparam and _parse_header are copied and modified from python2.7's cgi.py
# The original 2.7 version of this code did not correctly support some
# combinations of semicolons and double quotes.
# It has also been modified to support valueless parameters as seen in
# websocket extension negotiations, and to support non-ascii values in
# RFC 2231/5987 format.


def _parseparam(s: str) -> Generator[str, None, None]:
    while s[:1] == ";":
        s = s[1:]
        end = s.find(";")
        while end > 0 and (s.count('"', 0, end) - s.count('\\"', 0, end)) % 2:
            end = s.find(";", end + 1)
        if end < 0:
            end = len(s)
        f = s[:end]
        yield f.strip()
        s = s[end:]


def _parse_header(line: str) -> Tuple[str, Dict[str, str]]:
    r"""Parse a Content-type like header.

    Return the main content-type and a dictionary of options.

    >>> d = "form-data; foo=\"b\\\\a\\\"r\"; file*=utf-8''T%C3%A4st"
    >>> ct, d = _parse_header(d)
    >>> ct
    'form-data'
    >>> d['file'] == r'T\u00e4st'.encode('ascii').decode('unicode_escape')
    True
    >>> d['foo']
    'b\\a"r'
    """
    parts = _parseparam(";" + line)
    key = next(parts)
    # decode_params treats first argument special, but we already stripped key
    params = [("Dummy", "value")]
    for p in parts:
        i = p.find("=")
        if i >= 0:
            name = p[:i].strip().lower()
            value = p[i + 1 :].strip()
            params.append((name, native_str(value)))
    decoded_params = email.utils.decode_params(params)
    decoded_params.pop(0)  # get rid of the dummy again
    pdict = {}
    for name, decoded_value in decoded_params:
        value = email.utils.collapse_rfc2231_value(decoded_value)
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        pdict[name] = value
    return key, pdict


def _encode_header(key: str, pdict: Dict[str, str]) -> str:
    """Inverse of _parse_header.

    >>> _encode_header('permessage-deflate',
    ...     {'client_max_window_bits': 15, 'client_no_context_takeover': None})
    'permessage-deflate; client_max_window_bits=15; client_no_context_takeover'
    """
    if not pdict:
        return key
    out = [key]
    # Sort the parameters just to make it easy to test.
    for k, v in sorted(pdict.items()):
        if v is None:
            out.append(k)
        else:
            # TODO: quote if necessary.
            out.append(f"{k}={v}")
    return "; ".join(out)
