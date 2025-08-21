"""The module contains the escape module tests."""

import json
import unittest

from kate.core.escape import json_encode, to_unicode, utf8


class TestEscapeFunctions(unittest.TestCase):
    """The class implements the tests for escape utility functions."""

    def test_json_encode_serializes_to_json_and_escapes_closing_tags(self):
        """The function should have the possibility to encode data to JSON
        and escape the '</' sequence.
        """
        data = {'message': 'test', 'count': 5}
        result = json_encode(data)

        expected = json.dumps(data).replace('</', '<\\/')
        self.assertEqual(result, expected)

        data = {'message': '</script>'}
        result = json_encode(data)

        self.assertIn('<\\/script>', result)
        self.assertNotIn('</script>', result)

    def test_to_unicode_converts_supported_values_and_handles_none_and_invalid_types(self):
        """The function should have the possibility to convert supported input values to
        a Unicode string and handle invalid cases.
        """
        result = to_unicode('test')
        self.assertEqual(result, 'test')

        result = to_unicode(b'test')
        self.assertEqual(result, 'test')

        result = to_unicode(None)
        self.assertIsNone(result)

        with self.assertRaises(TypeError):
            to_unicode(123)

    def test_utf8_converts_supported_values_and_handles_none_and_invalid_types(self):
        """The function should have the possibility to convert supported input values to
        UTF-8 encoded bytes and handle invalid cases.
        """
        result = utf8(b'test')
        self.assertEqual(result, b'test')

        result = utf8('test')
        self.assertEqual(result, b'test')

        result = utf8(None)
        self.assertIsNone(result)

        with self.assertRaises(TypeError):
            utf8(123)
