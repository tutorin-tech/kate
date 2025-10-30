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

"""The module contains tests for VisualAttributesMixin."""

# ruff: noqa: S311, SLF001

import array
import random

from kate.constants import BLACK_AND_WHITE, BLINK_BIT, BOLD_BIT, REVERSE_BIT, UNDERLINE_BIT
from tests.helper import Helper


class TestVisualAttributesMixin(Helper):  # noqa: PLR0904
    """The class implements tests for VisualAttributesMixin."""

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

    def test_default_rendition(self):
        """The terminal should provide the default text rendition as BLACK_AND_WHITE."""
        term = self._terminal
        term._default_rendition()
        self.assertEqual(BLACK_AND_WHITE, term._sgr)

    def test_set_attribute(self):
        """Test setting attributes with _set_attribute."""
        term = self._terminal

        term._set_attribute(1)
        self.assertTrue(term._is_bit_set(BOLD_BIT, term._sgr))

        term._set_attribute(4)
        self.assertTrue(term._is_bit_set(UNDERLINE_BIT, term._sgr))

        term._set_attribute(24)
        self.assertFalse(term._is_bit_set(UNDERLINE_BIT, term._sgr))

        term._set_attribute(5)
        self.assertTrue(term._is_bit_set(BLINK_BIT, term._sgr))

        term._set_attribute(7)
        self.assertTrue(term._is_bit_set(REVERSE_BIT, term._sgr))

        # Stubs
        term._set_attribute(2)
        term._set_attribute(10)
        term._set_attribute(11)
        term._set_attribute(27)

    def test_set_bg_color(self):
        """The terminal should have the possibility to set the background color."""
        term = self._terminal

        for color in range(8):  # 0-7 are background colors
            term._set_bg_color(color)

            color_bits, _ = divmod(term._sgr, 0x10000000000)
            bg, _fg = divmod(color_bits, 16)
            self.assertEqual(color, bg)

    def test_set_fg_color(self):
        """The terminal should have the possibility to set the foreground color."""
        term = self._terminal

        for color in range(8):  # 0-7 are foreground colors
            term._set_fg_color(color)

            color_bits, _ = divmod(term._sgr, 0x10000000000)
            _bg, fg = divmod(color_bits, 16)
            self.assertEqual(color, fg)

    def test_set_fg_color_with_bold(self):
        """The terminal should switch to bright colors when bold is set."""
        term = self._terminal

        term._cap_bold()
        term._set_fg_color(1)  # red

        color_bits, _ = divmod(term._sgr, 0x10000000000)  # should be bright red
        _bg, fg = divmod(color_bits, 16)
        self.assertEqual(9, fg)

    def test_set_color_foreground(self):
        """The terminal should handle foreground color codes."""
        term = self._terminal

        for ansi_code in range(30, 38):  # 30-37 are ANSI foreground colors
            term._set_color(ansi_code)
            expected_color = ansi_code - 30

            color_bits, _ = divmod(term._sgr, 0x10000000000)
            _bg, fg = divmod(color_bits, 16)
            self.assertEqual(expected_color, fg)

    def test_set_color_background(self):
        """The terminal should handle background color codes."""
        term = self._terminal

        for ansi_code in range(40, 48):  # 40-47 are ANSI background colors
            term._set_color(ansi_code)
            expected_color = ansi_code - 40

            color_bits, _ = divmod(term._sgr, 0x10000000000)
            bg, _fg = divmod(color_bits, 16)
            self.assertEqual(expected_color, bg)

    def test_set_color_reset(self):
        """The terminal should reset colors with codes 0 and 39/49."""
        term = self._terminal

        term._set_color(31)
        term._set_color(0)  # reset
        self.assertEqual(BLACK_AND_WHITE, term._sgr)

        term._set_color(32)
        term._set_color(39)  # foreground reset
        self.assertEqual(BLACK_AND_WHITE, term._sgr)

        term._set_color(42)  # green background
        term._set_color(49)  # background reset
        self.assertEqual(BLACK_AND_WHITE, term._sgr)

    def test_set_color_pair(self):
        """The terminal should handle color pair combinations."""
        term = self._terminal

        term._set_color_pair(0, 10)
        self.assertEqual(BLACK_AND_WHITE, term._sgr)

        term._sgr = 0x10000000001
        term._set_color_pair(39, 49)  # reset
        self.assertEqual(BLACK_AND_WHITE, term._sgr)

    def test_set_color_pair_with_bold_and_bright_red(self):
        """The terminal should handle bold attribute and bright red foreground color."""
        term = self._terminal
        term._set_color_pair(1, 31)
        self.assertTrue(term._is_bit_set(BOLD_BIT, term._sgr))

        color_bits, _ = divmod(term._sgr, 0x10000000000)
        _bg, fg = divmod(color_bits, 16)
        self.assertEqual(9, fg)  # bright red foreground

    def test_set_color_pair_with_underline_and_green_bg(self):
        """The terminal should handle underline attribute and green background color."""
        term = self._terminal
        term._sgr = BLACK_AND_WHITE
        term._set_color_pair(4, 42)
        self.assertTrue(term._is_bit_set(UNDERLINE_BIT, term._sgr))

        color_bits, _ = divmod(term._sgr, 0x10000000000)
        bg, _fg = divmod(color_bits, 16)
        self.assertEqual(2, bg)  # green background

    def test_set_color_pair_with_reverse_and_blue_fg(self):
        """The terminal should handle reverse attribute and blue foreground color."""
        term = self._terminal
        term._sgr = BLACK_AND_WHITE
        term._set_color_pair(7, 34)
        self.assertTrue(term._is_bit_set(REVERSE_BIT, term._sgr))

        color_bits, _ = divmod(term._sgr, 0x10000000000)
        _bg, fg = divmod(color_bits, 16)
        self.assertEqual(4, fg)  # blue foreground

    def test_set_color_pair_with_blink_and_yellow_bg(self):
        """The terminal should handle blink attribute and yellow background color."""
        term = self._terminal
        term._sgr = BLACK_AND_WHITE
        term._set_color_pair(5, 43)
        self.assertTrue(term._is_bit_set(BLINK_BIT, term._sgr))

        color_bits, _ = divmod(term._sgr, 0x10000000000)
        bg, _fg = divmod(color_bits, 16)
        self.assertEqual(3, bg)  # yellow background

    def test_set_color_pair_with_dim_and_cyan_fg(self):
        """The terminal should handle dim attribute and cyan foreground color."""
        term = self._terminal
        term._sgr = BLACK_AND_WHITE
        term._set_color_pair(2, 36)

        color_bits, _ = divmod(term._sgr, 0x10000000000)
        _bg, fg = divmod(color_bits, 16)
        self.assertEqual(6, fg)  # cyan foreground
