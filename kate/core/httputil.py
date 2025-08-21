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

import collections.abc
import email.utils
from http.client import responses
import re

from kate.core.escape import native_str

# responses is unused in this file, but we re-export it to other files.
# Reference it so pyflakes doesn't complain.
responses

import typing
from typing import Tuple, Dict, Generator

if typing.TYPE_CHECKING:
    from typing import Deque  # noqa: F401
    from asyncio import Future  # noqa: F401
    import unittest  # noqa: F401

    # This can be done unconditionally in the base class of HTTPHeaders
    # after we drop support for Python 3.8.
    StrMutableMapping = collections.abc.MutableMapping[str, str]
else:
    StrMutableMapping = collections.abc.MutableMapping


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



class HTTPInputError(Exception):
    """Exception class for malformed HTTP requests or responses
    from remote sources.

    """

    pass


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
