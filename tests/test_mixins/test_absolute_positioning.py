"""The module contains tests related to absolute positioning of cursor."""

# ruff: noqa: S311, SLF001

import random

from tests.helper import Helper


class AbsolutePositioningTest(Helper):
    """The class implements the tests for `AbsolutePositioningMixin`."""

    def test_cap_cup(self):
        """The terminal should have the possibility to set the vertical and
        horizontal positions of the cursor to the specified values.
        """
        term = self._terminal

        # The cursor is at the left-most position.
        # Note that the y and x values start from 1.
        self._check_cap_cup((1, 1))
        self._check_cap_cup((term._cols, term._rows))

        rand_x = random.randint(1, term._right_most - 1)
        rand_y = random.randint(1, term._bottom_most - 1)
        self._check_cap_cup((rand_x, rand_y))

    def test_cap_hpa(self):
        """The terminal should have the possibility to set the horizontal
        position to the specified value.
        """
        term = self._terminal

        self._check_cap_hpa(1)
        self._check_cap_hpa(term._cols)

        rand_x = random.randint(2, term._cols - 1)
        self._check_cap_hpa(rand_x)

    def test_cap_vpa(self):
        """The terminal should have the possibility to set the vertical
        position of the cursor to the specified value.
        """
        term = self._terminal

        self._check_cap_vpa(1)
        self._check_cap_vpa(term._rows)

        rand_y = random.randint(1, term._rows - 1)
        self._check_cap_vpa(rand_y)
