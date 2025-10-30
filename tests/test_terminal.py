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

    def test_generate_html_basic_text(self):
        """Test generate_html with basic text output."""
        html = self._terminal.generate_html(b'Hello World')
        self.assertIn('<span class="b0 f7">Hello\xa0World</span>', html)

    def test_generate_html_control_characters(self):
        """Test generate_html processes control characters correctly."""
        self._terminal.generate_html(b'Hello\x0d' + b'World')  # carriage return
        self.assertEqual(self._terminal._cur_x, len(b'World'))

    def test_generate_html_newlines(self):
        """Test generate_html with newline characters."""
        html = self._terminal.generate_html(
            b'Line 1\n'
            b'Line 2\n'
            b'Line 3',
        )

        self.assertIn('<span class="b0 f7">Line\xa01', html)
        self.assertIn('Line\xa02', html)
        self.assertIn('Line\xa03', html)

        self.assertEqual(
            self._terminal._cur_x,
            len(b'Line 1') + len(b'Line 2') + len(b'Line 3'),
        )
        self.assertEqual(self._terminal._cur_y, 2)  # third line

    def test_generate_html_with_colors(self):
        """Test generate_html with color escape sequences."""
        html = self._terminal.generate_html(b'\x1b[31mRed Text' + b'\x1b[0m')
        self.assertIn('<span class="b0 f1">Red\xa0Text</span>', html)

    def test_generate_html_with_bold_attribute(self):
        """Test generate_html with bold text attribute."""
        html = self._terminal.generate_html(b'\x1b[1m' + b'Bold Text' + b'\x1b[0m')
        self.assertIn('<span class="b0 f15 bold">Bold\xa0Text</span>', html)

    def test_generate_html_with_underline_attribute(self):
        """Test generate_html with underline text attribute."""
        html = self._terminal.generate_html(b'\x1b[4mUnderlined' + b'\x1b[0m')
        self.assertIn('<span class="b0 f7 underline">Underlined</span>', html)

    def test_generate_html_with_reverse_attribute(self):
        """Test generate_html with reverse text attribute."""
        html = self._terminal.generate_html(b'\x1b[7m' + b'Reverse' + b'\x1b[0m')
        self.assertIn('<span class="b7 f0">Reverse</span>', html)

    def test_generate_html_with_blink_attribute(self):
        """Test generate_html with blink text attribute."""
        html = self._terminal.generate_html(b'\x1b[5m' + b'Blink' + b'\x1b[0m')
        self.assertIn('<span class="b0 f7 blink">Blink</span>', html)

    def test_generate_html_cursor_positioning(self):
        """Test generate_html with cursor positioning sequences."""
        self._terminal.generate_html(b'Hello' + b'\x1b[2;3H' + b'World')
        self.assertEqual(self._terminal._cur_x, 2 + len(b'World'))
        self.assertEqual(self._terminal._cur_y, 1)  # second line

    def test_generate_html_empty_buffer(self):
        """Test generate_html with empty buffer."""
        html = self._terminal.generate_html(b'')
        self.assertIn('<span class="b1 f7">\xa0\x00</span><span class="b0 f7">', html)

    def test_generate_html_unicode_characters(self):
        """Test generate_html with special Unicode characters and encoding."""
        html = self._terminal.generate_html('café'.encode())
        self.assertIn('café', html)

    def test_generate_html_html_escaping(self):
        """Test generate_html with characters needing HTML escaping."""
        html = self._terminal.generate_html(b'<>&"\'')
        self.assertIn('&lt;&gt;&amp;&quot;&#x27;', html)


if __name__ == '__main__':
    unittest.main()
