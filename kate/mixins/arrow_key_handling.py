"""The module contains mixin related to pressing arrow keys."""


class ArrowKeyHandlingMixin:
    """The mixin contains methods related to pressing arrow keys."""

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
