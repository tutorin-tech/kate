"""The module contains tests related to pressing arrow keys."""

# ruff: noqa: S311, SLF001

import random

from kate.test.helper import Helper


class ArrowKeyHandlingMixinTest(Helper):
    """The class implements the tests for `ArrowKeyHandlingMixin`."""

    def test_cap_kcub1(self):
        """The terminal should have the possibility to handle a Left Arrow
        key-press.
        """
        term = self._terminal

        self._check_cap_kcub1((0, 0))
        self._check_cap_kcub1((1, 0))
        self._check_cap_kcub1((term._right_most, 0))

        rand_x = random.randint(2, term._right_most - 1)
        self._check_cap_kcub1((rand_x, 0))

    def test_cap_kcud1(self):
        """The terminal should have the possibility to handle a Down Arrow
        key-press.
        """
        term = self._terminal

        self._check_cap_kcud1((0, 0), want_cur_y=1)
        self._check_cap_kcud1((0, term._bottom_most),
                              want_cur_y=term._bottom_most)

        rand_y = random.randint(1, term._bottom_most - 1)
        self._check_cap_kcud1((0, rand_y), want_cur_y=rand_y + 1)

    def test_cap_kcuu1(self):
        """The terminal should have the possibility to handle an Up Arrow
        key-press.
        """
        term = self._terminal

        self._check_cap_kcuu1((0, 0), term._top_most)
        self._check_cap_kcuu1((0, term._bottom_most), term._bottom_most - 1)

        rand_y = random.randint(1, term._bottom_most - 1)
        self._check_cap_kcuu1((0, rand_y), rand_y - 1)
