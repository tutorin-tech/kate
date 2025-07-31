"""The module contains tests related to clearing the screen."""

# ruff: noqa: S311, SLF001

import array
import random

from kate.constants import BLACK_AND_WHITE
from kate.tests.helper import Helper


class ScreenClearingTest(Helper):
    """The class implements the tests for `ScreenClearingMixin`."""

    def test_cap_ed(self):
        """The terminal should have the possibility to clear the screen from
        the current cursor position to the end of the screen.
        """
        term = self._terminal

        prompt = 'spam@ham:~$ '
        self._put_string(prompt, (0, 0))
        self._check_string(prompt, (0, 0), (len(prompt), 0))

        # Fill the rest of the screen with x.
        length = term._cols * term._rows - len(prompt)
        self._put_string(['x'] * length, (len(prompt), 0))

        # Clear the screen after the prompt till the end of the screen.
        term._cur_x = len(prompt)
        term._cur_y = 0
        term._cap_ed()

        # Check that the prompt was not corrupted.
        self._check_string(prompt, (0, 0), (len(prompt), 0))

        # Check that the screen was cleared correctly.
        want = array.array('Q', [BLACK_AND_WHITE] * length)
        got = term._peek((term._cur_x, 0),
                         (term._right_most, term._bottom_most),
                         inclusively=True)
        self.assertEqual(want, got)

    def test_cap_el(self):
        """The terminal should have the possibility to clear a line from the
        current cursor position to the end of the line.
        """
        term = self._terminal

        self._check_cap_el(['s'] * term._right_most, (0, 0))
        self._check_cap_el(['s'] * term._right_most, (term._right_most, 0))

        rand_x = random.randint(1, term._right_most - 1)
        self._check_cap_el(['s'] * term._right_most, (rand_x, 0))

    def test_cap_el1(self):
        """The terminal should have the possibility to clear a line from the
        beginning to the current cursor position.
        """
        term = self._terminal

        self._check_cap_el1(['s'] * term._right_most, (0, 0))
        self._check_cap_el1(['s'] * term._right_most, (term._right_most, 0))

        rand_x = random.randint(1, term._right_most - 1)
        self._check_cap_el1(['s'] * term._right_most, (rand_x, 0))
