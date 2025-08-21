"""The module contains the tests for the core HTTP utility module."""

import unittest

from kate.core.httputil import (
    HTTPInputError,
    _encode_header,
    _parse_header,
    parse_request_start_line,
)


class TestCoreHTTPUtility(unittest.TestCase):
    """The class implements the tests for the core HTTP utility module."""

    def test_encode_header_handles_empty_parameters(self):
        """The function should return original key when no parameters provided."""
        self.assertEqual('upgrade', _encode_header('upgrade', {}))

    def test_encode_header_renders_sorted_parameters(self):
        """The function should render parameters in sorted order."""
        params = {
            'client_no_context_takeover': None,
            'client_max_window_bits': 15,
        }
        encoded = _encode_header('permessage-deflate', params)

        expected = 'permessage-deflate; client_max_window_bits=15; client_no_context_takeover'
        self.assertEqual(expected, encoded)

    def test_parse_header_decodes_quoted_and_encoded_values(self):
        """The function should decode quoted and RFC 2231 encoded parameters."""
        header = r'form-data; foo="b\\a\"r"; file*=utf-8\'\'T%C3%A4st'
        key, params = _parse_header(header)

        self.assertEqual('form-data', key)
        self.assertEqual('b\\a"r', params['foo'])
        self.assertEqual('Täst', params['file'])

    def test_parse_header_handles_semicolons_inside_quotes(self):
        """The function should treat semicolons inside quoted values as literal characters."""
        header = 'form-data; filename="value;still"; foo=bar'
        _, params = _parse_header(header)

        self.assertEqual('value;still', params['filename'])
        self.assertEqual('bar', params['foo'])

    def test_parse_header_ignores_valueless_parameter(self):
        """The function should ignore parameters without explicit values."""
        header = 'permessage-deflate; client_no_context_takeover'
        _, params = _parse_header(header)

        self.assertEqual({}, params)

    def test_parse_request_start_line_rejects_malformed_line(self):
        """The function should raise HTTPInputError for malformed request lines."""
        with self.assertRaises(HTTPInputError):
            parse_request_start_line('INVALID_REQUEST')

    def test_parse_request_start_line_rejects_unsupported_version(self):
        """The function should raise HTTPInputError for versions other than HTTP/1.x."""
        with self.assertRaises(HTTPInputError):
            parse_request_start_line('GET / HTTP/2.0')

    def test_parse_request_start_line_returns_namedtuple(self):
        """The function should parse valid request line into a named tuple."""
        request_line = 'GET /index.html HTTP/1.1'
        result = parse_request_start_line(request_line)

        self.assertEqual('GET', result.method)
        self.assertEqual('/index.html', result.path)
        self.assertEqual('HTTP/1.1', result.version)
