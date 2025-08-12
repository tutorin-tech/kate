"""The module contains mixin related to cursor state."""


class CursorStateMixin:
    """The mixin contains methods related to cursor state."""

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
