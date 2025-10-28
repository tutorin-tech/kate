"""The module contains the tests for the core escape module."""

import json
import unittest

from kate.core.escape import json_encode, native_str, to_unicode, utf8


class TestCoreEscape(unittest.TestCase):
    """The class implements the tests for the core escape module."""

    def test_json_encode_escapes_script_tag(self):
        """The function should escape '</' substrings in the serialized output."""
        payload = '</script>'
        result = json_encode(payload)

        self.assertEqual('"<\\/script>"', result)

    def test_json_encode_matches_json_dumps_for_safe_values(self):
        """The function should match json.dumps for values without '</'."""
        data = {'status': 'ok', 'count': 3}
        self.assertEqual(json_encode(data), json.dumps(data))

    def test_native_str_aliases_to_unicode(self):
        """The function should behave the same as to_unicode."""
        data = b'value'
        self.assertEqual(native_str(data), to_unicode(data))

    def test_to_unicode_decodes_bytes(self):
        """The function should decode bytes to Unicode strings."""
        data = b'test'
        decoded = to_unicode(data)

        self.assertIsInstance(decoded, str)
        self.assertEqual(decoded, 'test')

    def test_to_unicode_passes_through_str_and_none(self):
        """The function should return Unicode strings and None unchanged."""
        text = 'sample'
        self.assertIs(text, to_unicode(text))
        self.assertIsNone(to_unicode(None))

    def test_to_unicode_rejects_unsupported_type(self):
        """The function should raise TypeError for unsupported inputs."""
        with self.assertRaises(TypeError):
            to_unicode(123.456)

    def test_utf8_passes_through_bytes_and_none(self):
        """The function should return bytes and None inputs unchanged."""
        payload = b'binary'
        self.assertIs(payload, utf8(payload))
        self.assertIsNone(utf8(None))

    def test_utf8_rejects_unsupported_type(self):
        """The function should raise TypeError for unsupported inputs."""
        with self.assertRaises(TypeError):
            utf8(123)

    def test_utf8_returns_bytes_for_string_input(self):
        """The function should encode Unicode strings to utf-8 bytes."""
        raw = 'test'
        encoded = utf8(raw)

        self.assertIsInstance(encoded, bytes)
        self.assertEqual(encoded, raw.encode('utf-8'))
