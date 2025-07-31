"""The module contains tests related to basic cursor movements."""

# ruff: noqa: S311, SLF001

import random

from kate.tests.helper import Helper


class BasicCursorMovementTest(Helper):
    """The class implements the tests for `BasicCursorMovementMixin`."""

    def test_cap_cr(self):
        """The terminal should have the possibility to do carriage return."""
        self._check_cap_cr((0, 0))
        self._check_cap_cr((self._terminal._right_most, 0))
        self._check_cap_cr((random.randint(1, self._terminal._right_most), 0))

    def test_cap_cub1(self):
        """The terminal should have the possibility to move the cursor left by
        1 position.
        """
        self._check_cap_cub1((0, 0))
        self._check_cap_cub1((1, 0))
        self._check_cap_cub1((self._terminal._right_most, 0))

        rand_x = random.randint(2, self._terminal._right_most - 1)
        self._check_cap_cub1((rand_x, 0))

    def test_cap_cuf(self):
        """The terminal should have the possibility to move the cursor right by
        a specified number of positions.
        """
        term = self._terminal

        # Move the cursor to the right-most position.
        term._cap_cuf(term._right_most)
        self.assertEqual(term._cur_x, term._right_most)
        self.assertFalse(term._eol)

        # Then move the cursor right by 1 position to check reaching the end of
        # the line.
        term._cap_cuf(1)
        self.assertTrue(term._eol)

    def test_cursor_down(self):
        """The terminal should have the possibility to move the cursor down by
        1 position.
        """
        self._check_cursor_down(0)
        self._check_cursor_down(self._terminal._bottom_most, top=True)

        rand_y = random.randint(1, self._terminal._bottom_most - 1)
        self._check_cursor_down(rand_y)

    def test_cursor_right(self):
        """The terminal should have the possibility to move the cursor right by
        1 position.
        """
        self._check_cursor_right(0)

        rand_x = random.randint(1, self._cols - 2)
        self._check_cursor_right(rand_x)

        self._check_cursor_right(self._terminal._right_most, eol=True)

    def test_cap_home(self):
        """The terminal should have the possibility to move the cursor to the
        home position.
        """
        term = self._terminal

        self._check_cap_home((0, 0))

        # The x position of the cursor is at the right-most position and
        # the end of the line was reached.
        self._put_string(['t'] * term._right_most, (0, 0))
        self._check_cap_home((term._right_most, term._bottom_most))

        rand_x = random.randint(1, term._right_most - 1)
        rand_y = random.randint(1, term._bottom_most - 1)
        self._check_cap_home((rand_x, rand_y))

    def test_cap_ht(self):
        """The terminal should have the possibility to tab to the next 8-space
        hardware tab stop.
        """
        term = self._terminal
        tab = 8

        # echo -e "\tHello"
        s = 'Hello'
        term._cap_ht()
        self._put_string(s, (term._cur_x, 0))
        # There must be 8 spaces at the beginning of the line.
        want = ('\x00' * tab) + s
        self._check_string(want, (0, 0), (len(s) + tab, 0))
        term._cap_rs1()

        # echo -e "Hello,\tWorld!"
        part1, part2 = 'Hello,', 'World!'
        self._put_string(part1, (0, 0))
        term._cap_ht()
        self._put_string(part2, (term._cur_x, 0))
        spaces = tab - len(part1)
        # There must be 2 spaces between 'Hello,' and 'World!' because 'Hello,'
        # consists of 6 characters (tab - 6 = 2).
        self.assertEqual(2, spaces)
        want = part1 + ('\x00' * spaces) + part2
        self._check_string(want, (0, 0), (len(want), 0))
        term._cap_rs1()

        # echo -e "Buzzword\tcontains 8 letters"
        part1, part2 = 'Buzzword', 'contains 8 letters'
        self._put_string(part1, (0, 0))
        term._cap_ht()
        self._put_string(part2, (term._cur_x, 0))
        # There must be 8 spaces between 'Buzzword' and 'contains 8 letters'
        # because 'Buzzword' consists of 8 characters.
        want = part1 + ('\x00' * tab) + part2
        self._check_string(want, (0, 0), (len(want), 0))
