"""The module contains the unit tests for the escape module."""

import json
import unittest

from kate.core.websocket.escape import json_encode, to_unicode, utf8


class TestEscapeFunctions(unittest.TestCase):
    """Test class for escape functions."""

    def test_utf8(self):
        """Test utf8 encoding."""
        result = utf8(b'test')
        self.assertEqual(result, b'test')

        result = utf8('test')
        self.assertEqual(result, b'test')

        result = utf8(None)
        self.assertIsNone(result)

        with self.assertRaises(TypeError):
            utf8(123)

    def test_to_unicode(self):
        """Test converting to unicode."""
        result = to_unicode('test')
        self.assertEqual(result, 'test')

        result = to_unicode(b'test')
        self.assertEqual(result, 'test')

        result = to_unicode(None)
        self.assertIsNone(result)

        with self.assertRaises(TypeError):
            to_unicode(123)

    def test_json_encode(self):
        """Test JSON encoding."""
        data = {'message': 'test', 'count': 5}
        result = json_encode(data)

        expected = json.dumps(data).replace('</', '<\\/')
        self.assertEqual(result, expected)

        data = {'message': '</script>'}
        result = json_encode(data)

        self.assertIn('<\\/script>', result)
        self.assertNotIn('</script>', result)
