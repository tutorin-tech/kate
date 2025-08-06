"""The module contains mixin related to operations on characters."""


class CharacterOperationsMixin:
    """The mixin contains methods related to operations on characters."""

    def _cap_dch(self, n):
        """Delete ``n`` number of characters."""
        cur_x, cur_y = self._cur_x, self._cur_y
        end = self._peek((cur_x, cur_y), (self._cols, cur_y))
        self._cap_el()
        self._poke((cur_x, cur_y), end[n:])

    def _cap_dch1(self):
        """Delete a character."""
        self._cap_dch(1)

    def _cap_ech(self, n):
        """Erase ``n`` number of characters."""
        self._zero((self._cur_x, self._cur_y), (self._cur_x + n, self._cur_y),
                   inclusively=True)

    def _cap_ich(self, n):
        """Insert ``n`` number of blank characters."""
        for i in range(n):
            self._scroll_right(self._cur_x + i, self._cur_y)
