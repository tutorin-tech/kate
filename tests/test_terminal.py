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

"""The module contains the terminal tests."""

# ruff: noqa: S311, SLF001

import random
import unittest

from tests.helper import Helper


class TestTerminal(Helper):
    """The class implements the terminal tests."""

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


if __name__ == '__main__':
    unittest.main()
