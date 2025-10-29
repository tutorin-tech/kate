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

"""The module contains tests for ScreenBufferMixin."""

# ruff: noqa: S311, SLF001

import array
import random

from kate.constants import BLACK_AND_WHITE
from tests.helper import Helper


class TestScreenBufferMixin(Helper):
    """The class implements tests for ScreenBufferMixin."""

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
