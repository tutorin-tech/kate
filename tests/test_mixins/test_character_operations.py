"""The module contains tests related to operations on characters."""

# ruff: noqa: S311, SLF001

import random

from tests.helper import Helper


class CharacterOperationsTest(Helper):
    """The class implements the tests for `CharacterOperationsMixin`."""

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
