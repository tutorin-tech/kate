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

"""The module contains tests for CoreMixin."""

# ruff: noqa: SLF001

from tests.helper import Helper


class TestCoreMixin(Helper):
    """The class implements tests for CoreMixin."""

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

    def test_exec_method_existing(self):
        """The terminal should execute existing methods through _exec_method."""
        term = self._terminal

        term._cur_x = 5  # move cursor to non-zero position
        initial_x = term._cur_x
        term._exec_method('cr')  # should execute _cap_cr

        self.assertEqual(0, term._cur_x)
        self.assertNotEqual(initial_x, term._cur_x)

    def test_exec_method_with_args(self):
        """The terminal should execute methods with arguments."""
        term = self._terminal

        term._cap_home()
        initial_x = term._cur_x
        term._exec_method('cuf', [5])  # should execute _cap_cuf(5)

        self.assertEqual(initial_x + 5, term._cur_x)

    def test_exec_method_nonexistent(self):
        """The terminal should handle non-existent methods gracefully."""
        term = self._terminal

        initial_x = term._cur_x
        term._exec_method('nonexistent')

        self.assertEqual(initial_x, term._cur_x)

    def test_ignore_method(self):
        """The terminal should have an ignore method that does nothing."""
        term = self._terminal

        initial_state = {
            'cur_x': term._cur_x,
            'cur_y': term._cur_y,
            'sgr': term._sgr,
            'eol': term._eol,
        }

        term._ignore()

        self.assertEqual(initial_state['cur_x'], term._cur_x)
        self.assertEqual(initial_state['cur_y'], term._cur_y)
        self.assertEqual(initial_state['sgr'], term._sgr)
        self.assertEqual(initial_state['eol'], term._eol)

    def test_exec_single_character_command(self):
        """The terminal should execute single character control sequences."""
        term = self._terminal

        term._cur_x = 5
        initial_x = term._cur_x
        term._buf = '\r'  # carriage return
        term._exec_single_character_command()

        self.assertEqual(0, term._cur_x)
        self.assertNotEqual(initial_x, term._cur_x)
        self.assertEqual('', term._buf)

    def test_exec_escape_sequence_basic(self):
        """The terminal should execute basic escape sequences."""
        term = self._terminal

        initial_x = term._cur_x
        term._buf = '\x1b[1C'  # move cursor right by 1
        term._exec_escape_sequence()

        self.assertEqual(initial_x + 1, term._cur_x)
        self.assertEqual('', term._buf)

    def test_exec_escape_sequence_with_params(self):
        """The terminal should execute parameterized escape sequences."""
        term = self._terminal

        initial_x = term._cur_x
        term._buf = '\x1b[5C'  # move cursor right by 5 (cuf)
        term._exec_escape_sequence()

        self.assertEqual(initial_x + 5, term._cur_x)
        self.assertEqual('', term._buf)

    def test_escape_sequence_buffer_reset(self):
        """The terminal should reset buffer after executing sequences."""
        term = self._terminal

        term._buf = '\x1b[H'  # home cursor
        self.assertEqual('\x1b[H', term._buf)

        term._exec_escape_sequence()
        self.assertEqual('', term._buf)

        term._buf = (
            '\x1b[1;2;3;4;5;6;7;8;9;10;11;12;13;14;1516;17;18;'
            '19;20;21;22;23;24;25;26;27;28;29;30;31;32;33C'
        )
        term._exec_escape_sequence()
        self.assertEqual('', term._buf)
