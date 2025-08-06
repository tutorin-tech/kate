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

import random
import unittest

from kate.constants import (
    BLACK_AND_WHITE,
    BLINK_BIT,
    BOLD_BIT,
    REVERSE_BIT,
    UNDERLINE_BIT,
)
from kate.test.helper import Helper


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

    def test_cap_csr(self):
        """The terminal should have the possibility to change the scrolling
        region.
        """
        self._check_cap_csr((1, 1))
        self._check_cap_csr((1, 2))
        self._check_cap_csr((2, 1))

        rand_top = random.randint(2, self._rows - 1)
        rand_bottom = random.randint(2, self._rows - 1)
        self._check_cap_csr((rand_top, rand_bottom))

        self._check_cap_csr((self._rows, self._rows))

    def test_cap_ind(self):
        """The terminal should have the possibility to move the cursor down by
        1 position.
        """
        self._terminal._cap_ind()
        self.assertEqual(1, self._terminal._cur_y)

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

    def test_cap_ri(self):
        """The terminal should have the possibility to scroll text down."""
        term = self._terminal

        self._check_cap_ri(['x'] * term._right_most, (0, 0))
        self._check_cap_ri(['x'] * term._right_most, (0, 1))

        rand_y = random.randint(2, term._bottom_most)
        self._check_cap_ri(['x'] * term._right_most, (0, rand_y))

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
