"""The module contains the core util tests."""

import unittest

from kate.core.util import _websocket_mask_python


class TestPythonMaskFunction(unittest.TestCase):
    """The class implements the tests for the websocket mask function."""

    @staticmethod
    def mask(mask, data):
        """Apply the Python websocket mask function to the given data with the specified mask."""
        return _websocket_mask_python(mask, data)

    def test_mask(self):
        """Test the websocket mask function with various inputs and expected outputs."""
        self.assertEqual(self.mask(b'abcd', b''), b'')
        self.assertEqual(self.mask(b'abcd', b'b'), b'\x03')
        self.assertEqual(self.mask(b'abcd', b'54321'), b'TVPVP')
        self.assertEqual(self.mask(b'ZXCV', b'98765432'), b'c`t`olpd')
        # Include test cases with \x00 bytes (to ensure that the C
        # extension isn't depending on null-terminated strings) and
        # bytes with the high bit set (to smoke out signedness issues).
        self.assertEqual(
            self.mask(b'\x00\x01\x02\x03', b'\xff\xfb\xfd\xfc\xfe\xfa'),
            b'\xff\xfa\xff\xff\xfe\xfb',
        )
        self.assertEqual(
            self.mask(b'\xff\xfb\xfd\xfc', b'\x00\x01\x02\x03\x04\x05'),
            b'\xff\xfa\xff\xff\xfb\xfe',
        )

    def test_mask_roundtrip(self):
        """Test that masking the result of masking recovers the original data."""
        mask = b'\x01\x02\x03\x04'
        data = b'hello websocket'

        masked = _websocket_mask_python(mask, data)
        self.assertEqual(_websocket_mask_python(mask, masked), data)
