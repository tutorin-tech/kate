"""The module contains the httputil module tests."""

import unittest

from kate.core.httputil import (
    HTTPInputError,
    RequestStartLine,
    _ABNF,
    _encode_header,
    _parse_header,
    _parseparam,
    parse_request_start_line,
)


class TestHTTPUtilityFunctions(unittest.TestCase):
    """The class implements the tests for HTTP utility helpers and ABNF patterns."""

    def test_abnf_field_name_accepts_valid_tokens_and_rejects_invalid(self):
        """The ABNF pattern for a header field name should accept valid tokens
        and reject invalid ones.
        """
        pattern = _ABNF.field_name
        self.assertTrue(pattern.fullmatch('Content-Type'))
        self.assertTrue(pattern.fullmatch('X-Custom-Header'))
        self.assertFalse(pattern.fullmatch('Invalid Header'))

    def test_abnf_method_accepts_standard_methods_and_rejects_invalid(self):
        """The ABNF pattern for an HTTP method should accept standard methods
        and reject invalid values.
        """
        pattern = _ABNF.method
        self.assertTrue(pattern.fullmatch('GET'))
        self.assertTrue(pattern.fullmatch('OPTIONS'))
        self.assertFalse(pattern.fullmatch('INVALID METHOD'))

    def test_abnf_request_line_matches_valid_and_rejects_invalid(self):
        """The ABNF pattern for a request line should match valid lines and
        reject invalid ones.
        """
        pattern = _ABNF.request_line
        self.assertTrue(pattern.fullmatch('GET /index.html HTTP/1.1'))
        self.assertTrue(pattern.fullmatch('POST /submit HTTP/1.0'))
        self.assertFalse(pattern.fullmatch('INVALID REQUEST LINE'))

    def test_abnf_uri_sub_delims_matches_expected_characters(self):
        """The ABNF pattern for URI sub-delimiters should match allowed characters
        and reject others.
        """
        pattern = _ABNF.uri_sub_delims
        self.assertTrue(pattern.fullmatch("'"))
        self.assertFalse(pattern.fullmatch('a'))

    def test_abnf_uri_unreserved_matches_expected_characters(self):
        """The ABNF pattern for URI unreserved characters should match allowed
        characters and reject others.
        """
        pattern = _ABNF.uri_unreserved
        self.assertTrue(pattern.fullmatch('~'))
        self.assertFalse(pattern.fullmatch('='))

    def test_encode_header_converts_non_string_values_to_strings(self):
        """The function should have the possibility to convert non-string
        parameter values to strings.
        """
        result = _encode_header("token", {"a": 1, "b": True, "c": 3.14})
        self.assertEqual(result, "token; a=1; b=True; c=3.14")

    def test_encode_header_encodes_mixed_parameters_sorted(self):
        """The function should have the possibility to encode value parameters and
        flag parameters in a sorted order.
        """
        params = {
            "server_max_window_bits": 10,
            "client_no_context_takeover": None,
            "client_max_window_bits": 15,
        }
        result = _encode_header("permessage-deflate", params)
        self.assertEqual(
            result,(
                "permessage-deflate; "
                "client_max_window_bits=15; "
                "client_no_context_takeover; "
                "server_max_window_bits=10"
            ),
        )

    def test_encode_header_returns_key_when_parameters_are_empty(self):
        """The function should have the possibility to return only the key when the parameter dictionary is empty."""
        self.assertEqual(
            _encode_header("permessage-deflate", {}),
            "permessage-deflate",
        )

    def test_parse_header_parses_quoted_parameter_values(self):
        """The header parser should have the possibility to extract parameters
        even when values are quoted.
        """
        header_value = 'multipart/form-data; boundary=""----WebKitFormBoundary7MA4YWxkTrZu0gW""'
        content_type, params = _parse_header(header_value)

        self.assertEqual(content_type, 'multipart/form-data')
        self.assertEqual(params['boundary'], '----WebKitFormBoundary7MA4YWxkTrZu0gW')

    def test_parse_header_returns_value_and_parameters(self):
        """The header parser should have the possibility to return a main value
        and a dictionary of parameters.
        """
        header_value = 'text/html; charset=utf-8'
        value, params = _parse_header(header_value)
        self.assertEqual(value, 'text/html')
        self.assertEqual(params['charset'], 'utf-8')

    def test_parse_header_returns_value_without_parameters(self):
        """The header parser should have the possibility to return a main value
        when no parameters are present.
        """
        header_value = 'text/html'
        result = _parse_header(header_value)
        self.assertEqual(result, ('text/html', {}))

    def test_parse_request_start_line_parses_valid_start_line(self):
        """The request line parser should have the possibility to parse a valid
        HTTP request start line.
        """
        line = 'GET /index.html HTTP/1.1'
        result = parse_request_start_line(line)

        self.assertEqual(result.method, 'GET')
        self.assertEqual(result.path, '/index.html')
        self.assertEqual(result.version, 'HTTP/1.1')

    def test_parse_request_start_line_raises_for_invalid_format(self):
        """The request line parser should raise an error when the format is invalid."""
        line = 'INVALID REQUEST LINE'
        with self.assertRaises(HTTPInputError):
            parse_request_start_line(line)

    def test_parse_request_start_line_raises_for_unsupported_version(self):
        """The request line parser should raise an error when the HTTP version is unsupported."""
        line = 'GET /index.html HTTP/2.0'
        with self.assertRaises(HTTPInputError):
            parse_request_start_line(line)

    def test_parseparam_extracts_parameters_from_header_tail(self):
        """The parameter parser should have the possibility to extract
        semicolon-separated parameters from a header tail.
        """
        params = list(_parseparam('; param1=value1; param2=value2'))
        self.assertEqual(params, ['param1=value1', 'param2=value2'])

    def test_parseparam_preserves_semicolons_inside_quoted_strings(self):
        """The parameter parser should have the possibility to preserve semicolons
        that are inside quoted strings.
        """
        test_string = '; param1="value;with;semicolons"; param2=simple; param3="another;test"'
        result = list(_parseparam(test_string))
        expected = [
            'param1="value;with;semicolons"',
            'param2=simple',
            'param3="another;test"',
        ]
        self.assertEqual(result, expected)

    def test_request_start_line_exposes_fields(self):
        """The RequestStartLine object should expose method, path, and version as attributes."""
        start_line = RequestStartLine('GET', '/index.html', 'HTTP/1.1')
        self.assertEqual(start_line.method, 'GET')
        self.assertEqual(start_line.path, '/index.html')
        self.assertEqual(start_line.version, 'HTTP/1.1')

    def test_request_start_line_serializes_to_dictionary(self):
        """The RequestStartLine object should provide a dictionary representation
        with its fields.
        """
        start_line = RequestStartLine('GET', '/index.html', 'HTTP/1.1')
        expected = {'method': 'GET', 'path': '/index.html', 'version': 'HTTP/1.1'}
        self.assertEqual(start_line._asdict(), expected)
