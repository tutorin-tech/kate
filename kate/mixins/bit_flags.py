"""The module contains mixin that modify internal flags or state."""

from kate.base import BaseTerminal


class BitFlagsMixin(BaseTerminal):
    """The mixin contains methods that modify internal flags or state."""

    def _clean_bit(self, bit):
        """Clean the specified `_sgr` bit."""
        self._sgr &= ~(1 << bit)

    @staticmethod
    def _is_bit_set(bit, value):
        """Check if the specified bit is set in the specified value."""
        return bool(value & (1 << bit))

    def _set_bit(self, bit):
        """Set the specified `_sgr` bit."""
        self._sgr |= 1 << bit
