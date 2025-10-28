"""The module provides a content operations mixin."""


class ContentMixin:
    """The mixin contains methods for handling content at both line and character levels."""

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

    def _cap_il1(self):
        """Add a new blank line."""
        self._cap_il(1)

    def _cap_csr(self, top, bottom):
        """Change the scrolling region.

        The ``top`` and ``bottom`` parameters are lines of the scrolling
        region. After executing the method, the cursor position is undefined.
        See _cap_sc and _cap_rc.

        The ``top`` and ``bottom`` values start from 1.
        """
        self._top_most = min(self._bottom_most, top - 1)
        self._bottom_most = min(self._bottom_most, bottom - 1)

        # `_bottom_most` must be greater than or equal to `_top_most`.
        self._bottom_most = max(self._top_most, self._bottom_most)

    def _cap_ind(self):
        """Scroll the screen up moving its content down."""
        self._cursor_down()

    def _cap_ri(self):
        """Scroll text down. See _cap_ind."""
        self._cur_y = max(self._top_most, self._cur_y - 1)
        if self._cur_y == self._top_most:
            self._scroll_down(self._top_most, self._bottom_most)

    def _cap_smir(self):
        """Enter Insert mode. See _cap_rmir."""

    def _cap_rmir(self):
        """Exit Insert mode. See _cap_smir."""
