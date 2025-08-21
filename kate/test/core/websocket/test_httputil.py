"""The module contains the unit tests for the httputil module."""

import calendar
import datetime
import email.utils
import unittest

from kate.core.websocket.httputil import (
    HTTPHeaders,
    HTTPInputError,
    RequestStartLine,
    ResponseStartLine,
    _ABNF,
    _get_content_range,
    _int_or_none,
    _normalize_header,
    _parse_header,
    _parse_request_range,
    _parseparam,
    format_timestamp,
    parse_request_start_line,
)


class TestHTTPHeaders(unittest.TestCase):
    """Test class for HTTPHeaders."""

    def test_init_empty(self):
        """Test HTTPHeaders initialization with no arguments."""
        headers = HTTPHeaders()
        self.assertEqual(len(headers), 0)

    def test_init_with_dict(self):
        """Test HTTPHeaders initialization with dictionary."""
        headers = HTTPHeaders({'Content-Type': 'text/html', 'Content-Length': '100'})
        self.assertEqual(headers['Content-Type'], 'text/html')
        self.assertEqual(headers['Content-Length'], '100')

    def test_init_with_copy_constructor(self):
        """Test HTTPHeaders initialization with copy constructor."""
        original = HTTPHeaders({'Content-Type': 'text/html'})
        copied = HTTPHeaders(original)
        self.assertEqual(copied['Content-Type'], 'text/html')

    def test_add_valid_header(self):
        """Test adding valid headers."""
        headers = HTTPHeaders()
        headers.add('Content-Type', 'text/html')
        headers.add('Set-Cookie', 'session_id=123')

        self.assertEqual(headers['Content-Type'], 'text/html')
        self.assertEqual(headers['Set-Cookie'], 'session_id=123')
        self.assertEqual(headers.get_list('Set-Cookie'), ['session_id=123'])

    def test_add_multiple_values(self):
        """Test adding multiple values for the same header."""
        headers = HTTPHeaders()
        headers.add('Set-Cookie', 'session_id=123')
        headers.add('Set-Cookie', 'theme=dark')

        self.assertEqual(headers['Set-Cookie'], 'session_id=123,theme=dark')
        self.assertEqual(headers.get_list('Set-Cookie'), ['session_id=123', 'theme=dark'])

    def test_add_invalid_header_name(self):
        """Test adding header with invalid name."""
        headers = HTTPHeaders()
        with self.assertRaises(HTTPInputError):
            headers.add('Invalid Header', 'value')

    def test_add_invalid_header_value(self):
        """Test adding header with invalid value."""
        headers = HTTPHeaders()
        with self.assertRaises(HTTPInputError):
            headers.add('Content-Type', 'text\0html')

    def test_add_with_chars_are_bytes_false(self):
        """Test adding header with _chars_are_bytes=False and forbidden characters."""
        headers = HTTPHeaders()
        with self.assertRaises(HTTPInputError):
            headers.add('X-Test', 'value\u0001', _chars_are_bytes=False)

        headers.add('X-Test', 'normal value', _chars_are_bytes=False)
        self.assertEqual(headers['X-Test'], 'normal value')

    def test_get_list_nonexistent_header(self):
        """Test getting list for nonexistent header."""
        headers = HTTPHeaders()
        self.assertEqual(headers.get_list('Nonexistent'), [])

    def test_get_all(self):
        """Test getting all header pairs."""
        headers = HTTPHeaders()
        headers.add('Content-Type', 'text/html')
        headers.add('Set-Cookie', 'session_id=123')
        headers.add('Set-Cookie', 'theme=dark')

        all_headers = list(headers.get_all())
        expected = [
            ('Content-Type', 'text/html'),
            ('Set-Cookie', 'session_id=123'),
            ('Set-Cookie', 'theme=dark'),
        ]
        self.assertEqual(all_headers, expected)

    def test_parse_line_valid(self):
        """Test parsing valid header line."""
        headers = HTTPHeaders()
        headers.parse_line('Content-Type: text/html')
        self.assertEqual(headers['Content-Type'], 'text/html')

    def test_parse_line_with_whitespace(self):
        """Test parsing header line with whitespace."""
        headers = HTTPHeaders()
        headers.parse_line('Content-Type:   text/html   ')
        self.assertEqual(headers['Content-Type'], 'text/html')

    def test_parse_line_continuation_without_previous_header(self):
        """Test parsing continuation line without previous header."""
        headers = HTTPHeaders()
        with self.assertRaises(HTTPInputError):
            headers.parse_line('  continuation without previous')

    def test_parse_line_continuation_with_chars_are_bytes_false(self):
        """Test parsing continuation line with _chars_are_bytes=False."""
        headers = HTTPHeaders()
        headers.parse_line('Content-Type:')

        headers.parse_line(' text/html', _chars_are_bytes=False)
        self.assertEqual(headers['Content-Type'], ' text/html')

        headers._last_key = 'Content-Type'
        with self.assertRaises(HTTPInputError):
            headers.parse_line('  html\u0001', _chars_are_bytes=False)

    def test_parse_line_continuation_with_chars_are_bytes_true(self):
        """Test parsing continuation line with _chars_are_bytes=True."""
        headers = HTTPHeaders()
        headers.parse_line('Content-Type:')

        headers.parse_line(' text/html')
        self.assertEqual(headers['Content-Type'], ' text/html')

        headers._last_key = 'Content-Type'
        with self.assertRaises(HTTPInputError):
            headers.parse_line('  html\u0001')

    def test_parse_line_invalid_no_colon(self):
        """Test parsing header line without colon."""
        headers = HTTPHeaders()
        with self.assertRaises(HTTPInputError):
            headers.parse_line('InvalidLineWithoutColon')

    def test_parse_multiple_headers(self):
        """Test parsing multiple headers from text."""
        header_text = 'Content-Type: text/html\r\nContent-Length: 100\r\n\r\n'
        headers = HTTPHeaders.parse(header_text)

        self.assertEqual(headers['Content-Type'], 'text/html')
        self.assertEqual(headers['Content-Length'], '100')

    def test_dict_interface(self):
        """Test dictionary interface methods."""
        headers = HTTPHeaders({'Content-Type': 'text/html'})
        self.assertEqual(headers['Content-Type'], 'text/html')

        headers['Content-Length'] = '100'
        self.assertEqual(headers['Content-Length'], '100')

        del headers['Content-Type']
        self.assertNotIn('Content-Type', headers)
        self.assertEqual(len(headers), 1)

        keys = list(iter(headers))
        self.assertEqual(keys, ['Content-Length'])

    def test_copy(self):
        """Test copying HTTPHeaders."""
        headers = HTTPHeaders({'Content-Type': 'text/html'})
        copied = headers.copy()

        self.assertEqual(copied['Content-Type'], 'text/html')
        self.assertIsNot(headers, copied)

    def test_str_representation(self):
        """Test string representation."""
        headers = HTTPHeaders()
        headers.add('Content-Type', 'text/html')
        headers.add('Content-Length', '100')

        result = str(headers)
        self.assertIn('Content-Type: text/html', result)
        self.assertIn('Content-Length: 100', result)

    def test_normalize_header_name(self):
        """Test header name normalization."""
        self.assertEqual(_normalize_header('content-type'), 'Content-Type')
        self.assertEqual(_normalize_header('CONTENT-TYPE'), 'Content-Type')
        self.assertEqual(_normalize_header('content-type'), 'Content-Type')


class TestHTTPUtilityFunctions(unittest.TestCase):
    """Test class for HTTP utility functions."""

    def test_format_timestamp_int(self):
        """Test formatting integer timestamp."""
        ts = 1609459200  # 2021-01-01 00:00:00 UTC
        result = format_timestamp(ts)
        expected = email.utils.formatdate(ts, usegmt=True)
        self.assertEqual(result, expected)

    def test_format_timestamp_float(self):
        """Test formatting float timestamp."""
        ts = 1609459200.5  # 2021-01-01 00:00:00.5 UTC
        result = format_timestamp(ts)
        expected = email.utils.formatdate(ts, usegmt=True)
        self.assertEqual(result, expected)

    def test_format_timestamp_datetime(self):
        """Test formatting datetime timestamp."""
        dt = datetime.datetime(2021, 1, 1, 0, 0, 0)
        result = format_timestamp(dt)
        ts = calendar.timegm(dt.utctimetuple())
        expected = email.utils.formatdate(ts, usegmt=True)
        self.assertEqual(result, expected)

    def test_format_timestamp_with_tuple(self):
        """Test format_timestamp with time tuple."""
        dt = (2021, 1, 1, 0, 0, 0, 0, 0, 0)
        result = format_timestamp(dt)
        expected_ts = calendar.timegm(dt)
        expected = email.utils.formatdate(expected_ts, usegmt=True)

        self.assertEqual(result, expected)

    def test_parse_header_with_quoted_values(self):
        """Test _parse_header with quoted parameter values."""
        header_value = 'multipart/form-data; boundary=""----WebKitFormBoundary7MA4YWxkTrZu0gW""'
        content_type, params = _parse_header(header_value)

        self.assertEqual(content_type, 'multipart/form-data')
        self.assertEqual(params['boundary'], '----WebKitFormBoundary7MA4YWxkTrZu0gW')

    def test_parseparam_with_quoted_semicolons(self):
        """Test _parseparam with semicolons inside quoted strings."""
        test_string = '; param1="value;with;semicolons"; param2=simple; param3="another;test"'
        result = list(_parseparam(test_string))
        expected = [
            'param1="value;with;semicolons"',
            'param2=simple',
            'param3="another;test"'
        ]

        self.assertEqual(result, expected)

    def test_format_timestamp_invalid_type(self):
        """Test formatting invalid timestamp type."""
        with self.assertRaises(TypeError):
            format_timestamp('invalid')

    def test_parse_request_start_line_valid(self):
        """Test parsing valid HTTP request start line."""
        line = 'GET /index.html HTTP/1.1'
        result = parse_request_start_line(line)

        self.assertEqual(result.method, 'GET')
        self.assertEqual(result.path, '/index.html')
        self.assertEqual(result.version, 'HTTP/1.1')

    def test_parse_request_start_line_invalid_format(self):
        """Test parsing invalid HTTP request start line format."""
        line = 'INVALID REQUEST LINE'
        with self.assertRaises(HTTPInputError):
            parse_request_start_line(line)

    def test_parse_request_start_line_unsupported_version(self):
        """Test parsing HTTP request with unsupported version."""
        line = 'GET /index.html HTTP/2.0'
        with self.assertRaises(HTTPInputError):
            parse_request_start_line(line)

    def test_parse_request_range_valid(self):
        """Test parsing valid Range header."""
        range_header = 'bytes=0-100'
        result = _parse_request_range(range_header)
        self.assertEqual(result, (0, 101))

    def test_parse_request_range_no_end(self):
        """Test parsing Range header with no end."""
        range_header = 'bytes=100-'
        result = _parse_request_range(range_header)
        self.assertEqual(result, (100, None))

    def test_parse_request_range_no_start(self):
        """Test parsing Range header with no start."""
        range_header = 'bytes=-100'
        result = _parse_request_range(range_header)
        self.assertEqual(result, (-100, None))

    def test_parse_request_range_start_only(self):
        """Test parsing Range header with only start."""
        range_header = 'bytes=100-'
        result = _parse_request_range(range_header)
        self.assertEqual(result, (100, None))

    def test_parse_request_range_zero_end(self):
        """Test parsing Range header with zero end."""
        range_header = 'bytes=-0'
        result = _parse_request_range(range_header)
        self.assertEqual(result, (None, 0))

    def test_parse_request_range_empty(self):
        """Test parsing empty Range header."""
        range_header = 'bytes='
        result = _parse_request_range(range_header)
        self.assertEqual(result, (None, None))

    def test_parse_request_range_invalid_unit(self):
        """Test parsing Range header with invalid unit."""
        range_header = 'invalid=0-100'
        result = _parse_request_range(range_header)
        self.assertIsNone(result)

    def test_parse_request_range_invalid_value(self):
        """Test parsing Range header with invalid value."""
        range_header = 'bytes=invalid-100'
        result = _parse_request_range(range_header)
        self.assertIsNone(result)

    def test_parse_request_range_multiple_ranges(self):
        """Test parsing Range header with multiple ranges."""
        range_header = 'bytes=1-2,6-10'
        result = _parse_request_range(range_header)
        self.assertIsNone(result)

    def test_get_content_range(self):
        """Test generating Content-Range header."""
        result = _get_content_range(0, 100, 500)
        self.assertEqual(result, 'bytes 0-99/500')

    def test_int_or_none_valid(self):
        """Test _int_or_none with valid integer."""
        self.assertEqual(_int_or_none('123'), 123)

    def test_int_or_none_empty(self):
        """Test _int_or_none with empty string."""
        self.assertIsNone(_int_or_none(''))

    def test_int_or_none_none(self):
        """Test _int_or_none with None."""
        self.assertIsNone(_int_or_none(' '))

    def test_parse_header_simple(self):
        """Test parsing simple header."""
        header_value = 'text/html'
        result = _parse_header(header_value)
        self.assertEqual(result, ('text/html', {}))

    def test_parse_header_with_params(self):
        """Test parsing header with parameters."""
        header_value = 'text/html; charset=utf-8'
        result = _parse_header(header_value)
        self.assertEqual(result[0], 'text/html')
        self.assertEqual(result[1]['charset'], 'utf-8')

    def test_parseparam(self):
        """Test parsing parameters from header."""
        params = list(_parseparam('; param1=value1; param2=value2'))
        self.assertEqual(params, ['param1=value1', 'param2=value2'])


class TestABNFPatterns(unittest.TestCase):
    """Test class for ABNF patterns."""

    def test_uri_unreserved(self):
        """Test URI unreserved characters pattern."""
        pattern = _ABNF.uri_unreserved
        self.assertTrue(pattern.fullmatch('~'))
        self.assertFalse(pattern.fullmatch('='))

    def test_uri_sub_delims(self):
        """Test URI sub-delimiters pattern."""
        pattern = _ABNF.uri_sub_delims
        self.assertTrue(pattern.fullmatch("'"))
        self.assertFalse(pattern.fullmatch('a'))

    def test_field_name(self):
        """Test field name pattern."""
        pattern = _ABNF.field_name
        self.assertTrue(pattern.fullmatch('Content-Type'))
        self.assertTrue(pattern.fullmatch('X-Custom-Header'))
        self.assertFalse(pattern.fullmatch('Invalid Header'))  # Space not allowed

    def test_method(self):
        """Test HTTP method pattern."""
        pattern = _ABNF.method
        self.assertTrue(pattern.fullmatch('GET'))
        self.assertTrue(pattern.fullmatch('POST'))
        self.assertTrue(pattern.fullmatch('OPTIONS'))
        self.assertFalse(pattern.fullmatch('INVALID METHOD'))  # Space not allowed

    def test_request_line(self):
        """Test HTTP request line pattern."""
        pattern = _ABNF.request_line
        self.assertTrue(pattern.fullmatch('GET /index.html HTTP/1.1'))
        self.assertTrue(pattern.fullmatch('POST /submit HTTP/1.0'))
        self.assertFalse(pattern.fullmatch('INVALID REQUEST LINE'))


class TestRequestStartLine(unittest.TestCase):
    """Test class for RequestStartLine named tuple."""

    def test_creation(self):
        """Test creating RequestStartLine."""
        start_line = RequestStartLine('GET', '/index.html', 'HTTP/1.1')
        self.assertEqual(start_line.method, 'GET')
        self.assertEqual(start_line.path, '/index.html')
        self.assertEqual(start_line.version, 'HTTP/1.1')

    def test_as_dict(self):
        """Test converting RequestStartLine to dict."""
        start_line = RequestStartLine('GET', '/index.html', 'HTTP/1.1')
        as_dict = start_line._asdict()
        expected = {'method': 'GET', 'path': '/index.html', 'version': 'HTTP/1.1'}
        self.assertEqual(as_dict, expected)


class TestResponseStartLine(unittest.TestCase):
    """Test class for ResponseStartLine named tuple."""

    def test_creation(self):
        """Test creating ResponseStartLine."""
        start_line = ResponseStartLine('HTTP/1.1', 200, 'OK')
        self.assertEqual(start_line.version, 'HTTP/1.1')
        self.assertEqual(start_line.code, 200)
        self.assertEqual(start_line.reason, 'OK')

    def test_as_dict(self):
        """Test converting ResponseStartLine to dict."""
        start_line = ResponseStartLine('HTTP/1.1', 200, 'OK')
        as_dict = start_line._asdict()
        expected = {'version': 'HTTP/1.1', 'code': 200, 'reason': 'OK'}
        self.assertEqual(as_dict, expected)
