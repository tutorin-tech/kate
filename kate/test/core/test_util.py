"""The module contains the utility functions tests."""

import unittest

from kate.core.util import _websocket_mask_python


class TestWebSocketMaskPython(unittest.TestCase):
    """The class implements the WebSocket mask utility tests."""

    def test_mask_application_with_empty_data(self):
        """The function should return empty bytes when data is empty."""
        mask = b'\x00\x00\x00\x00'
        data = b''
        result = _websocket_mask_python(mask, data)
        self.assertEqual(result, b'')

    def test_mask_application_with_single_byte_data(self):
        """The function should correctly apply mask to single byte data."""
        mask = b'\x0f\x0f\x0f\x0f'
        data = b'\xf0'
        result = _websocket_mask_python(mask, data)
        self.assertEqual(result, b'\xff')

    def test_mask_application_with_full_mask_cycle(self):
        """The function should correctly apply mask when data length equals mask length."""
        mask = b'\x0f\x0f\x0f\x0f'
        data = b'\xf0\xf0\xf0\xf0'
        result = _websocket_mask_python(mask, data)
        self.assertEqual(result, b'\xff\xff\xff\xff')

    def test_mask_application_with_partial_mask_cycle(self):
        """The function should correctly apply mask when data length is not multiple of mask length."""
        mask = b'\x0f\x0f\x0f\x0f'
        data = b'\xf0\xf0\xf0\xf0\xf0'
        result = _websocket_mask_python(mask, data)
        self.assertEqual(result, b'\xff\xff\xff\xff\xff')

    def test_mask_application_with_multiple_mask_cycles(self):
        """The function should correctly apply mask when data spans multiple mask cycles."""
        mask = b'\x01\x02\x03\x04'
        data = b'\x10\x20\x30\x40\x50\x60\x70\x80'
        result = _websocket_mask_python(mask, data)
        expected = bytes([0x10 ^ 0x01, 0x20 ^ 0x02, 0x30 ^ 0x03, 0x40 ^ 0x04,
                         0x50 ^ 0x01, 0x60 ^ 0x02, 0x70 ^ 0x03, 0x80 ^ 0x04])
        self.assertEqual(result, expected)

    def test_mask_application_with_zero_mask(self):
        """The function should return original data when mask is all zeros."""
        mask = b'\x00\x00\x00\x00'
        data = b'test data'
        result = _websocket_mask_python(mask, data)
        self.assertEqual(result, data)

    def test_mask_application_with_all_ones_mask(self):
        """The function should invert all bits when mask is all ones."""
        mask = b'\xff\xff\xff\xff'
        data = b'\x00\x11\x22\x33'
        result = _websocket_mask_python(mask, data)
        self.assertEqual(result, b'\xff\xee\xdd\xcc')

    def test_mask_application_round_trip(self):
        """The function should restore original data when mask is applied twice."""
        mask = b'\x1a\x2b\x3c\x4d'
        data = b'test data for round trip'

        masked = _websocket_mask_python(mask, data)
        unmasked = _websocket_mask_python(mask, masked)

        self.assertEqual(unmasked, data)

    def test_mask_application_with_different_masks(self):
        """The function should produce different results for different masks on same data."""
        data = b'test data'
        mask1 = b'\x01\x02\x03\x04'
        mask2 = b'\x05\x06\x07\x08'

        result1 = _websocket_mask_python(mask1, data)
        result2 = _websocket_mask_python(mask2, data)

        self.assertNotEqual(result1, result2)
