"""The module provides a mixin for working directly with the internal screen buffer."""

import array

from kate.constants import BLACK_AND_WHITE


class ScreenBufferMixin:
    """The mixin contains methods for direct interaction with the internal screen buffer."""

    def _peek(self, left_border, right_border, *, inclusively=False):
        """Capture and returns a rectangular region of the screen between
        ``left_border`` and ``right_border``.

        The ``left_border`` and ``right_border`` arguments must be tuples or
        lists of coordinates ``(x1, y1)`` and ``(x2, y2)``, respectively.

        The name of the method was inherited from AjaxTerm, developers of
        which, in turn, inherited it from BASIC. See _poke.
        """
        x1, y1 = left_border
        x2, y2 = right_border
        begin = self._cols * y1 + x1
        end = self._cols * y2 + x2 + (1 if inclusively else 0)
        return self._screen[begin:end]

    def _poke(self, pos, s):
        """Put the specified slice ``s`` on the screen staring at the position
        ``pos``.

        The ``pos`` argument must be a tuple or list of coordinates ``(x, y)``.

        The name of the method was inherited from AjaxTerm, developers of
        which, in turn, inherited it from BASIC. See _peek.
        """
        x, y = pos
        begin = self._cols * y + x
        self._screen[begin:begin + len(s)] = s

    def _zero(self, left_border, right_border, *, inclusively=False):
        """Clear the area from ``left_border`` to ``right_border``.

        The ``left_border`` and ``right_border`` arguments must be tuples or
        lists of coordinates ``(x1, y1)`` and ``(x2, y2)``, respectively.
        """
        x1, y1 = left_border
        x2, y2 = right_border
        begin = self._cols * y1 + x1
        end = self._cols * y2 + x2 + (1 if inclusively else 0)
        length = end - begin  # the length of the area which have to be cleared
        self._screen[begin:end] = array.array('Q', [BLACK_AND_WHITE] * length)
        return length

    def _scroll_down(self, y1, y2):
        """Move the area specified by coordinates 0, ``y1`` and 0, ``y2`` down
        1 row.
        """
        line = self._peek((0, y1), (self._cols, y2 - 1))
        self._poke((0, y1 + 1), line)
        self._zero((0, y1), (self._cols, y1))

    def _scroll_right(self, x, y):
        """Move a piece of a row specified by coordinates ``x`` and ``y``
        right by 1 position.
        """
        self._poke((x + 1, y), self._peek((x, y), (self._cols, y)))
        self._zero((x, y), (x, y), inclusively=True)

    def _scroll_up(self, y1, y2):
        """Move the area specified by coordinates 0, ``y1`` and 0, ``y2`` up 1
        row.
        """
        area = self._peek((0, y1), (self._right_most, y2), inclusively=True)
        self._poke((0, y1 - 1), area)  # move the area up 1 row (y1 - 1)
        self._zero((0, y2), (self._cols, y2))
