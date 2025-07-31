"""The module contains tests related to scrolling control."""

# ruff: noqa: S311, SLF001

import random

from kate.tests.helper import Helper


class ScrollingControlTest(Helper):
    """The class implements the tests for `ScrollingControlMixin`."""

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

    def test_cap_ri(self):
        """The terminal should have the possibility to scroll text down."""
        term = self._terminal

        self._check_cap_ri(['x'] * term._right_most, (0, 0))
        self._check_cap_ri(['x'] * term._right_most, (0, 1))

        rand_y = random.randint(2, term._bottom_most)
        self._check_cap_ri(['x'] * term._right_most, (0, rand_y))
