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

"""The module contains tests for CursorMixin."""

# ruff: noqa: S311, SLF001

import random

from tests.helper import Helper


class TestCursorMixin(Helper):
    """The class implements tests for CursorMixin."""

    def test_cursor_down(self):
        """The terminal should have the possibility to move the cursor down by
        1 position.
        """
        self._check_cursor_down(0)
        self._check_cursor_down(self._terminal._bottom_most, top=True)

        rand_y = random.randint(1, self._terminal._bottom_most - 1)
        self._check_cursor_down(rand_y)

    def test_cursor_right(self):
        """The terminal should have the possibility to move the cursor right by
        1 position.
        """
        self._check_cursor_right(0)

        rand_x = random.randint(1, self._cols - 2)
        self._check_cursor_right(rand_x)

        self._check_cursor_right(self._terminal._right_most, eol=True)

    def test_cap_cr(self):
        """The terminal should have the possibility to do carriage return."""
        self._check_cap_cr((0, 0))
        self._check_cap_cr((self._terminal._right_most, 0))
        self._check_cap_cr((random.randint(1, self._terminal._right_most), 0))

    def test_cap_cvvis(self):
        """The terminal should have the possibility to make the cursor visible."""
        term = self._terminal

        term._cap_civis()
        self.assertFalse(term._cur_visible)

        term._cap_cvvis()
        self.assertTrue(term._cur_visible)

    def test_cap_civis(self):
        """The terminal should have the possibility to make the cursor invisible."""
        term = self._terminal
        self.assertTrue(term._cur_visible)

        term._cap_civis()
        self.assertFalse(term._cur_visible)

        term._cap_cvvis()
        self.assertTrue(term._cur_visible)

    def test_cap_cub1(self):
        """The terminal should have the possibility to move the cursor left by
        1 position.
        """
        self._check_cap_cub1((0, 0))
        self._check_cap_cub1((1, 0))
        self._check_cap_cub1((self._terminal._right_most, 0))

        rand_x = random.randint(2, self._terminal._right_most - 1)
        self._check_cap_cub1((rand_x, 0))

    def test_cap_cud(self):
        """The terminal should have the possibility to move the cursor down by
        a specified number of lines.
        """
        term = self._terminal

        self._check_cap_cud((0, 0), 1)
        self._check_cap_cud((term._right_most, 0), 1)

        self._check_cap_cud((0, 0), 3)
        self._check_cap_cud((term._right_most, 0), 3)

        lines_to_bottom = term._bottom_most
        self._check_cap_cud((0, 0), lines_to_bottom)

        self._check_cap_cud((0, term._bottom_most - 1), 2, want_bottom=True)
        self._check_cap_cud((0, term._bottom_most), 1, want_bottom=True)

        rand_x = random.randint(0, term._right_most)
        rand_y = random.randint(0, term._bottom_most - 3)
        rand_n = random.randint(1, 3)
        self._check_cap_cud((rand_x, rand_y), rand_n)

    def test_cap_cuf(self):
        """The terminal should have the possibility to move the cursor right by
        a specified number of positions.
        """
        term = self._terminal

        # Move the cursor to the right-most position.
        term._cap_cuf(term._right_most)
        self.assertEqual(term._cur_x, term._right_most)
        self.assertFalse(term._eol)

        # Then move the cursor right by 1 position to check reaching the end of
        # the line.
        term._cap_cuf(1)
        self.assertTrue(term._eol)

    def test_cap_cup(self):
        """The terminal should have the possibility to set the vertical and
        horizontal positions of the cursor to the specified values.
        """
        term = self._terminal

        # The cursor is at the left-most position.
        # Note that the y and x values start from 1.
        self._check_cap_cup((1, 1))
        self._check_cap_cup((term._cols, term._rows))

        rand_x = random.randint(1, term._right_most - 1)
        rand_y = random.randint(1, term._bottom_most - 1)
        self._check_cap_cup((rand_x, rand_y))

    def test_cap_home(self):
        """The terminal should have the possibility to move the cursor to the
        home position.
        """
        term = self._terminal

        self._check_cap_home((0, 0))

        # The x position of the cursor is at the right-most position and
        # the end of the line was reached.
        self._put_string(['t'] * term._right_most, (0, 0))
        self._check_cap_home((term._right_most, term._bottom_most))

        rand_x = random.randint(1, term._right_most - 1)
        rand_y = random.randint(1, term._bottom_most - 1)
        self._check_cap_home((rand_x, rand_y))

    def test_cap_hpa(self):
        """The terminal should have the possibility to set the horizontal
        position to the specified value.
        """
        term = self._terminal

        self._check_cap_hpa(1)
        self._check_cap_hpa(term._cols)

        rand_x = random.randint(2, term._cols - 1)
        self._check_cap_hpa(rand_x)

    def test_cap_ht(self):
        """The terminal should have the possibility to tab to the next 8-space
        hardware tab stop.
        """
        term = self._terminal
        tab = 8

        # echo -e "\tHello"
        s = 'Hello'
        term._cap_ht()
        self._put_string(s, (term._cur_x, 0))
        # There must be 8 spaces at the beginning of the line.
        want = ('\x00' * tab) + s
        self._check_string(want, (0, 0), (len(s) + tab, 0))
        term._cap_rs1()

        # echo -e "Hello,\tWorld!"
        part1, part2 = 'Hello,', 'World!'
        self._put_string(part1, (0, 0))
        term._cap_ht()
        self._put_string(part2, (term._cur_x, 0))
        spaces = tab - len(part1)
        # There must be 2 spaces between 'Hello,' and 'World!' because 'Hello,'
        # consists of 6 characters (tab - 6 = 2).
        self.assertEqual(2, spaces)
        want = part1 + ('\x00' * spaces) + part2
        self._check_string(want, (0, 0), (len(want), 0))
        term._cap_rs1()

        # echo -e "Buzzword\tcontains 8 letters"
        part1, part2 = 'Buzzword', 'contains 8 letters'
        self._put_string(part1, (0, 0))
        term._cap_ht()
        self._put_string(part2, (term._cur_x, 0))
        # There must be 8 spaces between 'Buzzword' and 'contains 8 letters'
        # because 'Buzzword' consists of 8 characters.
        want = part1 + ('\x00' * tab) + part2
        self._check_string(want, (0, 0), (len(want), 0))

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

    def test_cap_kcuf1(self):
        """The terminal should have the possibility to handle a Right Arrow
        key-press.
        """
        term = self._terminal

        self._check_cap_kcuf1((0, 0))
        self._check_cap_kcuf1((term._right_most - 1, 0))
        self._check_cap_kcuf1((term._right_most, 0), want_eol=True)

        rand_x = random.randint(1, term._right_most - 2)
        self._check_cap_kcuf1((rand_x, 0))

    def test_cap_kcuu1(self):
        """The terminal should have the possibility to handle an Up Arrow
        key-press.
        """
        term = self._terminal

        self._check_cap_kcuu1((0, 0), term._top_most)
        self._check_cap_kcuu1((0, term._bottom_most), term._bottom_most - 1)

        rand_y = random.randint(1, term._bottom_most - 1)
        self._check_cap_kcuu1((0, rand_y), rand_y - 1)

    def test_cap_rc(self):
        """The terminal should have the possibility to restore the cursor to
        the last saved position.
        """
        term = self._terminal
        term._cur_x = term._right_most - 1

        # Put a character to move the cursor to the right-most position.
        term._echo('e')

        # After putting another character we will reach the end of the line.
        term._echo('g')
        self.assertTrue(term._eol)

        cur_x_bck = term._cur_x
        term._cap_sc()  # save the cursor current position.

        # Put one more character to move the cursor to the next line.
        term._echo('g')

        term._cap_rc()  # restore a previously saved cursor position.
        self.assertEqual(cur_x_bck, term._cur_x)
        self.assertTrue(term._eol)

    def test_cap_sc(self):
        """The terminal should have the possibility to save the current cursor
        position.
        """
        term = self._terminal
        x = random.randint(0, term._right_most)
        y = random.randint(0, term._bottom_most)
        term._cur_x, term._cur_y = x, y
        term._cap_sc()

        self.assertEqual(x, term._cur_x_bak)
        self.assertEqual(y, term._cur_y_bak)

    def test_cap_vpa(self):
        """The terminal should have the possibility to set the vertical
        position of the cursor to the specified value.
        """
        term = self._terminal

        self._check_cap_vpa(1)
        self._check_cap_vpa(term._rows)

        rand_y = random.randint(1, term._rows - 1)
        self._check_cap_vpa(rand_y)
