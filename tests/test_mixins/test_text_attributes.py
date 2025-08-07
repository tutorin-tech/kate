"""The module contains tests related to text attributes."""

# ruff: noqa: SLF001


from kate.constants import BLACK_AND_WHITE, BLINK_BIT, BOLD_BIT, REVERSE_BIT, UNDERLINE_BIT
from tests.helper import Helper


class TextAttributesTest(Helper):
    """The class implements the tests for `TextAttributesMixin`."""

    def test_cap_bold(self):
        """The terminal should have the possibility to produce bold text."""
        term = self._terminal
        term._cap_bold()
        self.assertTrue(term._is_bit_set(BOLD_BIT, term._sgr))

    def test_cap_smul_rmul(self):
        """The terminal should have the possibility to enter and exit
        Underline mode.
        """
        term = self._terminal
        term._cap_smul()
        self.assertTrue(term._is_bit_set(UNDERLINE_BIT, term._sgr))
        term._cap_rmul()
        self.assertFalse(term._is_bit_set(UNDERLINE_BIT, term._sgr))

    def test_cap_blink(self):
        """The terminal should have the possibility to produce blinking text."""
        term = self._terminal
        term._cap_blink()
        self.assertTrue(term._is_bit_set(BLINK_BIT, term._sgr))

    def test_cap_rev(self):
        """The terminal should have the possibility to enable Reverse Video mode."""
        term = self._terminal
        term._cap_rev()
        self.assertTrue(term._is_bit_set(REVERSE_BIT, term._sgr))

    def test_cap_smso(self):
        """The terminal should have the possibility to enter Standout mode."""

    def test_cap_op(self):
        """The terminal should have the possibility to set default color-pair
        to the original one.
        """
        self._terminal._sgr = None
        self._terminal._cap_op()
        self.assertEqual(BLACK_AND_WHITE, self._terminal._sgr)

    def test_cap_sgr0(self):
        """The terminal should have the possibility to turn off all attributes."""
        self._terminal._sgr = None
        self._terminal._cap_sgr0()
        self.assertEqual(BLACK_AND_WHITE, self._terminal._sgr)
