"""The module contains mixin related to scrolling control."""


class ScrollingControlMixin:
    """The mixin contains methods related to scrolling control."""

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
