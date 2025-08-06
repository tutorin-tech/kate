"""The module contains mixin related to operations on lines."""


class LineOperationsMixin:
    """The mixin contains methods related to operations on lines."""

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
