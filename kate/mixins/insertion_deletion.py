"""The module contains mixin related to insertion and deletion lines or characters."""

from kate.base import BaseTerminal


class InsertDeleteMixin(BaseTerminal):
    """The mixin contains methods related to insertion and deletion lines
    or characters.

    Note: Mind the inheriting order since this mixin requires methods
    from ScreenBufferMixin.
    """

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

    def _cap_ed(self):
        """Clear the screen from the current cursor position to the end of the
        screen.
        """
        self._zero((self._cur_x, self._cur_y), (self._cols, self._rows - 1))

    def _cap_el(self):
        """Clear a line from the current cursor position to the end of the
        line without moving the cursor. See _cap_el1.
        """
        self._zero((self._cur_x, self._cur_y), (self._cols, self._cur_y))

    def _cap_el1(self):
        """Clear a line from the beginning to the current cursor position,
        inclusive. The cursor is not moved. See _cap_el.
        """
        self._zero((0, self._cur_y), (self._cur_x, self._cur_y),
                   inclusively=True)

    def _cap_dl(self, n):
        """Delete ``n`` number of lines.

        On the one hand, the specification says that the dl capability should
        delete ``n`` number of lines, on the other hand, in the reality, dl
        just scrolls up ``n`` number of lines. Notice, that dl should work
        together with another capability that will put the cursor on the
        line that is going to be deleted. For example, in tests dl works
        together with the home capability, but it doesn't mean that the
        capabilities are always used together.
        """
        if self._top_most <= self._cur_y <= self._bottom_most:
            for _ in range(n):
                self._scroll_up(self._cur_y + 1, self._bottom_most)

    def _cap_dl1(self):
        """Delete a line."""
        self._cap_dl(1)

    def _cap_il(self, n):
        """Add ``n`` number of new blank lines."""
        for _ in range(n):
            if self._cur_y < self._bottom_most:
                self._scroll_down(self._cur_y, self._bottom_most)

    def _cap_ich(self, n):
        """Insert ``n`` number of blank characters."""
        for i in range(n):
            self._scroll_right(self._cur_x + i, self._cur_y)

    def _cap_il1(self):
        """Add a new blank line."""
        self._cap_il(1)

    def _cap_rmir(self):
        """Exit Insert mode. See _cap_smir."""

    def _cap_smir(self):
        """Enter Insert mode. See _cap_rmir."""
