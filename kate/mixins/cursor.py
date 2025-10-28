"""The module provides a cursor management mixin."""


class CursorMixin:
    """The mixin contains methods for cursor handling."""

    def _cap_cvvis(self):
        """Make the cursor visible. See _cap_civis."""
        self._cur_visible = True

    def _cap_civis(self):
        """Make the cursor invisible. See _cap_cvvis."""
        self._cur_visible = False

    def _cap_sc(self):
        """Save the current cursor position. See _cap_rc."""
        self._cur_x_bak = self._cur_x
        self._cur_y_bak = self._cur_y

    def _cap_rc(self):
        """Restore the cursor to the last saved position. See _cap_sc."""
        self._cur_x = self._cur_x_bak
        self._cur_y = self._cur_y_bak
        self._eol = self._cur_x == self._right_most

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

    def _cap_cup(self, y, x):
        """Set the vertical and horizontal positions of the cursor to ``y``
        and ``x``, respectively. See _cap_vpa and _cap_hpa.

        The ``y`` and ``x`` values start from 1.
        """
        self._cap_vpa(y)
        self._cap_hpa(x)

    def _cap_hpa(self, x):
        """Set the horizontal position of the cursor to ``x``. See _cap_vpa.

        The ``x`` value starts from 1.
        """
        self._cur_x = min(self._right_most, x - 1)
        self._eol = False  # it's necessary to reset _eol after preceding echo

    def _cap_vpa(self, y):
        """Set the vertical position of the cursor to ``y``. See _cap_hpa.

        The ``y`` value starts from 1.
        """
        self._cur_y = min(self._bottom_most, y - 1)

    def _cap_kcub1(self):
        """Handle a Left Arrow key-press."""
        self._cur_x = max(0, self._cur_x - 1)
        self._eol = False

    def _cap_kcud1(self):
        """Handle a Down Arrow key-press."""
        self._cap_cud(1)

    def _cap_kcuf1(self):
        """Handle a Right Arrow key-press."""
        self._cap_cuf(1)

    def _cap_kcuu1(self):
        """Handle an Up Arrow key-press."""
        self._cur_y = max(self._top_most, self._cur_y - 1)

    def _cap_kb2(self):
        """Handle a Center key-press on keypad."""
        # xterm and Linux console have the kb2 capability, but screen doesn't.
        # Some terminal emulators even handle it in spite of the seeming
        # uselessness of the capability.
        # It's been decided to have a do-nothing handler for kb2.

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
