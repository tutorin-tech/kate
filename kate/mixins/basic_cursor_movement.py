"""The module contains mixin related to basic cursor movements."""


class BasicCursorMovementMixin:
    """The mixin contains methods related to basic cursor movements."""

    def _cap_cr(self):
        """Do carriage return."""
        self._eol = False
        self._cur_x = 0

    def _cap_cub1(self):
        """Move the cursor left by 1 position.

        Usually the method acts as a handler for a Backspace key-press.
        """
        self._cur_x = max(0, self._cur_x - 1)

    def _cap_cud(self, n):
        """Move the cursor down ``n`` number of lines."""
        self._cur_y = min(self._bottom_most, self._cur_y + n)

    def _cap_cuf(self, n):
        """Move the cursor right by ``n`` number of positions."""
        for _ in range(n):
            self._cursor_right()

    def _cap_home(self):
        """Move the cursor to the home position."""
        self._cur_x = 0
        self._cur_y = 0
        self._eol = False

    def _cap_ht(self):
        """Tab to the next 8-space hardware tab stop."""
        x = self._cur_x + 8
        q, _ = divmod(x, 8)
        self._cur_x = (q * 8) % self._cols

    def _cursor_down(self):
        """Move the cursor down by 1 position. If the cursor reaches the
        bottom of the screen, its content moves up 1 row.
        """
        if self._top_most <= self._cur_y <= self._bottom_most:
            self._eol = False
            q, r = divmod(self._cur_y + 1, self._bottom_most + 1)
            if q:
                self._scroll_up(self._top_most + 1, self._bottom_most)
                self._cur_y = self._bottom_most
            else:
                self._cur_y = r

    def _cursor_right(self):
        """Move the cursor right by 1 position."""
        q, r = divmod(self._cur_x + 1, self._cols)
        if q:
            self._eol = True
        else:
            self._cur_x = r
