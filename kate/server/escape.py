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

"""Escaping/unescaping methods for HTML, JSON, URLs, and others.

Also includes a few other miscellaneous string manipulation functions that
have crept in over time.

Many functions in this module have near-equivalents in the standard library
(the differences mainly relate to handling of bytes and unicode strings,
and were more relevant in Python 2). In new code, the standard library
functions are encouraged instead of this module where applicable. See the
docstrings on each function for details.
"""

import json
import urllib.parse

from kate.server.util import unicode_type

from typing import Union, Any, Optional, Dict, List


# The fact that json_encode wraps json.dumps is an implementation detail.
# Please see https://github.com/tornadoweb/tornado/pull/706
# before sending a pull request that adds **kwargs to this function.
def json_encode(value: Any) -> str:
    """JSON-encodes the given Python object.

    Equivalent to `json.dumps` with the additional guarantee that the output
    will never contain the character sequence ``</`` which can be problematic
    when JSON is embedded in an HTML ``<script>`` tag.
    """
    # JSON permits but does not require forward slashes to be escaped.
    # This is useful when json data is emitted in a <script> tag
    # in HTML, as it prevents </script> tags from prematurely terminating
    # the JavaScript.  Some json libraries do this escaping by default,
    # although python's standard library does not, so we do it here.
    # http://stackoverflow.com/questions/1580647/json-why-are-forward-slashes-escaped
    return json.dumps(value).replace("</", "<\\/")


def url_unescape(
    value: Union[str, bytes], encoding: Optional[str] = "utf-8", plus: bool = True
) -> Union[str, bytes]:
    """Decodes the given value from a URL.

    The argument may be either a byte or unicode string.

    If encoding is None, the result will be a byte string and this function is equivalent to
    `urllib.parse.unquote_to_bytes` if ``plus=False``.  Otherwise, the result is a unicode string in
    the specified encoding and this function is equivalent to either `urllib.parse.unquote_plus` or
    `urllib.parse.unquote` except that this function also accepts `bytes` as input.

    If ``plus`` is true (the default), plus signs will be interpreted as spaces (literal plus signs
    must be represented as "%2B").  This is appropriate for query strings and form-encoded values
    but not for the path component of a URL.  Note that this default is the reverse of Python's
    urllib module.

    .. versionadded:: 3.1
       The ``plus`` argument
    """
    if encoding is None:
        if plus:
            # unquote_to_bytes doesn't have a _plus variant
            value = to_basestring(value).replace("+", " ")
        return urllib.parse.unquote_to_bytes(value)
    else:
        unquote = urllib.parse.unquote_plus if plus else urllib.parse.unquote
        return unquote(to_basestring(value), encoding=encoding)


def parse_qs_bytes(
    qs: Union[str, bytes], keep_blank_values: bool = False, strict_parsing: bool = False
) -> Dict[str, List[bytes]]:
    """Parses a query string like urlparse.parse_qs,
    but takes bytes and returns the values as byte strings.

    Keys still become type str (interpreted as latin1 in python3!)
    because it's too painful to keep them as byte strings in
    python3 and in practice they're nearly always ascii anyway.
    """
    # This is gross, but python3 doesn't give us another way.
    # Latin1 is the universal donor of character encodings.
    if isinstance(qs, bytes):
        qs = qs.decode("latin1")
    result = urllib.parse.parse_qs(
        qs, keep_blank_values, strict_parsing, encoding="latin1", errors="strict"
    )
    encoded = {}
    for k, v in result.items():
        encoded[k] = [i.encode("latin1") for i in v]
    return encoded


_UTF8_TYPES = (bytes, type(None))


def utf8(value: Union[None, str, bytes]) -> Optional[bytes]:
    """Converts a string argument to a byte string.

    If the argument is already a byte string or None, it is returned unchanged.
    Otherwise it must be a unicode string and is encoded as utf8.
    """
    if isinstance(value, _UTF8_TYPES):
        return value
    if not isinstance(value, unicode_type):
        raise TypeError("Expected bytes, unicode, or None; got %r" % type(value))
    return value.encode("utf-8")


_TO_UNICODE_TYPES = (unicode_type, type(None))


def to_unicode(value: Union[None, str, bytes]) -> Optional[str]:
    """Converts a string argument to a unicode string.

    If the argument is already a unicode string or None, it is returned
    unchanged.  Otherwise it must be a byte string and is decoded as utf8.
    """
    if isinstance(value, _TO_UNICODE_TYPES):
        return value
    if not isinstance(value, bytes):
        raise TypeError("Expected bytes, unicode, or None; got %r" % type(value))
    return value.decode("utf-8")


# to_unicode was previously named _unicode not because it was private,
# but to avoid conflicts with the built-in unicode() function/type
_unicode = to_unicode

# When dealing with the standard library across python 2 and 3 it is
# sometimes useful to have a direct conversion to the native string type
native_str = to_unicode
to_basestring = to_unicode
