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

"""The module contains tests for ContentMixin."""

# ruff: noqa: S311, SLF001

import random

from tests.helper import Helper


class TestContentMixin(Helper):
    """The class implements tests for ContentMixin."""

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

    def test_cap_dch(self):
        """The terminal should have the possibility to delete the specified
        number of characters.
        """
        term = self._terminal

        greeting = 'Hello, World!'
        self._check_cap_dch(greeting, 7)  # remove 'Hello, '

        self._check_cap_dch(greeting, 0)
        self._check_cap_dch(['a'] * term._right_most, term._right_most)
        self._check_cap_dch(['b'] * term._cols, term._cols)

        # Remove a character.

        s = self._get_random_string(term._cols)
        self._put_string(s, (0, 0))
        self._check_string(s, (0, 0), (len(s), 0))

        term._cur_x = random.randint(0, term._right_most)
        term._cap_dch(1)

        want = s[:term._cur_x] + s[term._cur_x + 1:]
        self._check_string(want, (0, 0), (len(want), 0))

    def test_cap_dch1(self):
        """The terminal should have the possibility to delete a character."""
        term = self._terminal

        # Test deleting a single character from a string
        s = self._get_random_string(term._cols)
        self._put_string(s, (0, 0))
        self._check_string(s, (0, 0), (len(s), 0))

        # Delete first character
        term._cur_x = 0
        term._cap_dch1()
        want = s[1:]
        self._check_string(want, (0, 0), (len(want), 0))

        # Reset and test deleting middle character
        term._cap_rs1()
        self._put_string(s, (0, 0))
        term._cur_x = random.randint(1, term._right_most - 1)
        term._cap_dch1()
        want = s[:term._cur_x] + s[term._cur_x + 1:]
        self._check_string(want, (0, 0), (len(want), 0))

    def test_cap_dl(self):
        """The terminal should have the possibility to delete ``n`` number of
        lines.
        """
        term = self._terminal

        self._check_cap_dl(0, [(['f'] * term._cols, (0, 0))])
        self._check_cap_dl(1, [(['f'] * term._cols, (0, 0))])

        self._check_cap_dl(1, [
            (['t'] * term._cols, (0, 0)),
            (['a'] * term._cols, (0, 1)),
        ])

        self._check_cap_dl(2, [
            (['t'] * term._cols, (0, 0)),
            (['k'] * term._cols, (0, 1)),
        ])

        self._check_cap_dl(2, [
            (['f'] * term._cols, (0, 0)),
            (['s'] * term._cols, (0, 1)),
            (['k'] * term._cols, (0, 2)),
        ])

        self._check_cap_dl(1, [
            (['f'] * term._cols, (0, 0)),
            (['s'] * term._cols, (0, 1)),
            (['k'] * term._cols, (0, 2)),
        ])

        self._check_cap_dl(0, [
            (['f'] * term._cols, (0, 0)),
            (['s'] * term._cols, (0, 1)),
            (['k'] * term._cols, (0, 2)),
        ])

        lines_number = random.randint(2, term._bottom_most)
        lines = [(['a'] * term._cols, (0, i)) for i in range(lines_number)]

        self._check_cap_dl(random.randint(0, lines_number), lines)

    def test_cap_dl1(self):
        """The terminal should have the possibility to delete a single line."""
        term = self._terminal

        lines = [
            (['a'] * term._cols, (0, 0)),
            (['b'] * term._cols, (0, 1)),
            (['c'] * term._cols, (0, 2)),
        ]
        self._check_cap_dl1(lines)

    def test_cap_ech(self):
        """The terminal should have the possibility to erase the specified
        number of characters.
        """
        term = self._terminal

        self._check_cap_ech(['a'] * term._right_most, (0, 0), 0)
        self._check_cap_ech(['a'] * term._right_most, (0, 0), term._right_most)

        rand_x = random.randint(1, term._right_most - 1)
        self._check_cap_ech(['a'] * term._right_most, (0, 0), rand_x)

    def test_cap_ich(self):
        """The terminal should have the possibility to insert the specified
        number of blank characters.
        """
        term = self._terminal

        self._put_string(['x'] * self._cols, (0, 0))
        term._cur_x = term._cur_y = 0

        n = random.randint(0, term._right_most)
        # Insert n blank characters at the beginning of the first line.
        term._cap_ich(n)

        blank_characters = ['\x00'] * n
        want = blank_characters + ['x'] * (self._cols - n)
        self._check_string(want, (0, 0), (term._cols, 0))

    def test_cap_il1(self):
        """The terminal should have the possibility to add a new blank line."""
        term = self._terminal

        self._check_cap_il1(['s'] * term._right_most, (0, 0))
        self._check_cap_il1(['s'] * term._right_most, (0, term._bottom_most))

        rand_y = random.randint(1, term._bottom_most - 1)
        self._check_cap_il1(['s'] * term._right_most, (0, rand_y))

    def test_cap_ri(self):
        """The terminal should have the possibility to scroll text down."""
        term = self._terminal

        self._check_cap_ri(['x'] * term._right_most, (0, 0))
        self._check_cap_ri(['x'] * term._right_most, (0, 1))

        rand_y = random.randint(2, term._bottom_most)
        self._check_cap_ri(['x'] * term._right_most, (0, rand_y))

    def test_cap_ind(self):
        """The terminal should have the possibility to move the cursor down by
        1 position.
        """
        self._terminal._cap_ind()
        self.assertEqual(1, self._terminal._cur_y)
