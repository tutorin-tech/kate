"""The module contains tests related to operations on lines."""

# ruff: noqa: S311, SLF001

import random

from tests.helper import Helper


class LineOperationsTest(Helper):
    """The class implements the tests for `LineOperationsMixin`."""

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

    def test_cap_il1(self):
        """The terminal should have the possibility to add a new blank line."""
        term = self._terminal

        self._check_cap_il1(['s'] * term._right_most, (0, 0))
        self._check_cap_il1(['s'] * term._right_most, (0, term._bottom_most))

        rand_y = random.randint(1, term._bottom_most - 1)
        self._check_cap_il1(['s'] * term._right_most, (0, rand_y))
