# Copyright 2016 Dmitriy Shilin <sdadeveloper@gmail.com>
# Copyright 2016 Evgeny Golyshev <eugulixes@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""The module contains the capability tests."""

# ruff: noqa: S311, SLF001

import array
import random
import unittest

from kate.constants import (
    BLACK_AND_WHITE,
    BLINK_BIT,
    BOLD_BIT,
    REVERSE_BIT,
    UNDERLINE_BIT,
)
from tests.helper import Helper


class TestCapabilities(Helper):
    """The class implements the capability tests."""

    def test_echo(self):
        """The terminal should have the possibility to put the specified
        character on the screen and move the cursor right by 1 position.
        """
        term = self._terminal

        self._check_echo('d', (0, 0))

        rand_cur_x = random.randint(1, term._right_most - 1)
        rand_cur_y = random.randint(1, term._bottom_most - 1)
        self._check_echo('r', (rand_cur_x, rand_cur_y))

        self._check_echo('a', (term._right_most, rand_cur_y), eol=True)

        self._check_echo('p', (term._right_most, term._bottom_most), eol=True)

    def test_echo_eol(self):
        """The terminal should have the possibility to move the cursor to the
        next line when the current position of the cursor is at the end of a
        line.
        """
        term = self._terminal
        term._cur_x = term._right_most - 1

        # Put a character to move the cursor to the right-most position.
        term._echo('e')

        # After putting another character we will reach the end of the line.
        term._echo('g')
        self.assertTrue(term._eol)

        # After putting one more character the cursor will be moved to the
        # next line.
        term._echo('g')
        self.assertEqual(1, term._cur_x)
        self.assertEqual(1, term._cur_y)
        self.assertFalse(term._eol)

    def test_zero(self):
        """The terminal should have the possibility to clear the area from a
        left border starting at position x1, y1 to a right border starting at
        position x2, y2.
        """
        term = self._terminal

        self._check_zero(['s'] * term._right_most, (0, 0))
        self._check_zero(['p'] * term._right_most, (0, term._bottom_most))
        self._check_zero(['m'] * term._right_most * term._bottom_most, (0, 0))

        rand_x = random.randint(1, self._cols - 2)
        rand_y = random.randint(1, term._bottom_most - 1)
        rand_len = random.randint(1, term._right_most - rand_x)
        self._check_zero(['a'] * rand_len, (rand_x, rand_y))

    def test_scroll_up(self):
        """The terminal should have the possibility to move an area by
        1 line up.
        """
        term = self._terminal

        self._check_scroll_up(['f'] * term._cols, (0, 1))

        rand_y = random.randint(2, term._bottom_most - 1)
        self._check_scroll_up(['r'] * term._cols, (0, rand_y))

        # TODO: add a test case for checking scrolling up the last line # noqa: FIX002, TD002, TD003

    def test_scroll_down(self):
        """The terminal should have the possibility to move an area by
        1 line down.
        """
        term = self._terminal

        self._check_scroll_down(['f'] * term._right_most, (0, 0))
        self._check_scroll_down(['l'] * term._right_most,
                                (0, term._bottom_most - 1))

        rand_y = random.randint(2, term._bottom_most - 2)
        self._check_scroll_down(['r'] * term._right_most, (0, rand_y))

    def test_scroll_right(self):
        """The terminal should have the possibility to move an area by
        1 position right.
        """
        term = self._terminal

        self._check_scroll_right('test', (0, 0))

        s = 'test'
        self._check_scroll_right(s,
                                 (random.randint(1, term._right_most - len(s)),
                                  random.randint(1, term._bottom_most)))

    def test_peek(self):
        """The terminal should have the possibility to capture the area of the
        screen from a left border starting at position x1, y1 to a right border
        starting at position x2, y2.
        """
        term = self._terminal

        self._check_peek(['s'] * term._right_most, (0, 0))
        self._check_peek(['s'] * term._right_most, (0, term._bottom_most))

        rand_y = random.randint(1, term._bottom_most - 1)
        self._check_peek(['s'] * term._right_most, (0, rand_y))

    def test_peek_inclusively(self):
        """The terminal should have the possibility to capture the area of the
        screen from a left border starting at position x1, y1 to a right border
        starting at position x2, y2 inclusive.
        """
        term = self._terminal

        start = 3
        end = 7
        zeros = array.array('Q', [0] * (end - start))

        # The last '0' will be on the 6th position.
        term._screen[start:end] = zeros

        # Get an area from the 3rd to the 6th character.
        got = term._peek((start, 0), (end, 0))
        self.assertEqual(zeros, got)

        # Get an area from the 3rd to the 7th character.
        got = term._peek((start, 0), (end, 0), inclusively=True)
        zeros.append(BLACK_AND_WHITE)
        self.assertEqual(zeros, got)

    def test_poke(self):
        """The terminal should have the possibility to put the specified slice
        on the screen staring at the specified position.
        """
        term = self._terminal
        zeros = array.array('Q', [0] * term._right_most)

        self._check_poke(zeros, (0, 0))

        rand_y = random.randint(1, term._bottom_most - 1)
        self._check_poke(zeros, (0, rand_y))

        self._check_poke(zeros, (0, term._bottom_most))

    def test_cap_blink(self):
        """The terminal should have the possibility to produce blinking text."""
        term = self._terminal
        term._cap_blink()
        self.assertTrue(term._is_bit_set(BLINK_BIT, term._sgr))

    def test_cap_bold(self):
        """The terminal should have the possibility to produce bold text."""
        term = self._terminal
        term._cap_bold()
        self.assertTrue(term._is_bit_set(BOLD_BIT, term._sgr))

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

    def test_cap_op(self):
        """The terminal should have the possibility to set default color-pair
        to the original one.
        """
        self._terminal._sgr = None
        self._terminal._cap_op()
        self.assertEqual(BLACK_AND_WHITE, self._terminal._sgr)

    def test_cap_rev(self):
        """The terminal should have the possibility to enable Reverse Video mode."""
        term = self._terminal
        term._cap_rev()
        self.assertTrue(term._is_bit_set(REVERSE_BIT, term._sgr))

    def test_cap_rs1(self):
        """The terminal should have the possibility to completely reset to sane
        modes.
        """
        # Do some useless work.
        self._terminal._echo('a')
        self._terminal._cursor_right()
        self._terminal._cursor_down()
        self._terminal._scroll_down(0, self._terminal._bottom_most)

        # Reset the terminal to sane modes.
        self._terminal._cap_rs1()
        self.assertEqual(0, self._terminal._cur_x)
        self.assertEqual(0, self._terminal._cur_y)
        self.assertFalse(self._terminal._eol)

    def test_cap_sgr0(self):
        """The terminal should have the possibility to turn off all attributes."""
        self._terminal._sgr = None
        self._terminal._cap_sgr0()
        self.assertEqual(BLACK_AND_WHITE, self._terminal._sgr)

    def test_cap_smso(self):
        """The terminal should have the possibility to enter Standout mode."""

    def test_cap_smul_rmul(self):
        """The terminal should have the possibility to enter and exit
        Underline mode.
        """
        term = self._terminal
        term._cap_smul()
        self.assertTrue(term._is_bit_set(UNDERLINE_BIT, term._sgr))
        term._cap_rmul()
        self.assertFalse(term._is_bit_set(UNDERLINE_BIT, term._sgr))


if __name__ == '__main__':
    unittest.main()
