"""The module contains tests related to cursor state."""

# ruff: noqa: S311, SLF001

import random

from tests.helper import Helper


class CursorStateTest(Helper):
    """The class implements the tests for `CursorStateMixin`."""

    def test_cap_sc(self):
        """The terminal should have the possibility to save the current cursor
        position.
        """
        term = self._terminal
        x = random.randint(0, term._right_most)
        y = random.randint(0, term._bottom_most)
        term._cur_x, term._cur_y = x, y
        term._cap_sc()

        self.assertEqual(x, term._cur_x_bak)
        self.assertEqual(y, term._cur_y_bak)

    def test_cap_rc(self):
        """The terminal should have the possibility to restore the cursor to
        the last saved position.
        """
        term = self._terminal
        term._cur_x = term._right_most - 1

        # Put a character to move the cursor to the right-most position.
        term._echo('e')

        # After putting another character we will reach the end of the line.
        term._echo('g')
        self.assertTrue(term._eol)

        cur_x_bck = term._cur_x
        term._cap_sc()  # save the cursor current position.

        # Put one more character to move the cursor to the next line.
        term._echo('g')

        term._cap_rc()  # restore a previously saved cursor position.
        self.assertEqual(cur_x_bck, term._cur_x)
        self.assertTrue(term._eol)
