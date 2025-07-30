# Copyright 2013-2016 Evgeny Golyshev <eugulixes@gmail.com>
# Copyright 2016 Dmitriy Shilin <sdadeveloper@gmail.com>
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

"""The module contains the terminal implementation."""

import html

from kate import mixins
from kate.base import BaseTerminal
from kate.constants import (
    BLINK_BIT,
    BOLD_BIT,
    MAGIC_NUMBER,
    REVERSE_BIT,
    UNDERLINE_BIT,
)


class Terminal(
    mixins.BitFlagsMixin,
    mixins.ScreenBufferMixin,
    mixins.ExecutionMixin,
    mixins.TextAttributesMixin,
    BaseTerminal,
):
    """The class implements a terminal."""

    #
    # Internal methods.
    #

    def _cap_civis(self):
        """Make the cursor invisible. See _cap_cvvis."""
        self._cur_visible = False

    def _cap_cr(self):
        """Do carriage return."""
        self._eol = False
        self._cur_x = 0

    def _cap_cub1(self):
        """Move the cursor left by 1 position.

        Usually the method acts as a handler for a Backspace key-press.
        """
        self._cur_x = max(0, self._cur_x - 1)

    def _cap_cud(self, n):
        """Move the cursor down ``n`` number of lines."""
        self._cur_y = min(self._bottom_most, self._cur_y + n)

    def _cap_cuf(self, n):
        """Move the cursor right by ``n`` number of positions."""
        for _ in range(n):
            self._cursor_right()

    def _cap_cup(self, y, x):
        """Set the vertical and horizontal positions of the cursor to ``y``
        and ``x``, respectively. See _cap_vpa and _cap_hpa.

        The ``y`` and ``x`` values start from 1.
        """
        self._cap_vpa(y)
        self._cap_hpa(x)

    def _cap_cvvis(self):
        """Make the cursor visible. See _cap_civis."""
        self._cur_visible = True

    def _cap_dch(self, n):
        """Delete ``n`` number of characters."""
        cur_x, cur_y = self._cur_x, self._cur_y
        end = self._peek((cur_x, cur_y), (self._cols, cur_y))
        self._cap_el()
        self._poke((cur_x, cur_y), end[n:])

    def _cap_dch1(self):
        """Delete a character."""
        self._cap_dch(1)

    def _cap_dl(self, n):
        """Delete ``n`` number of lines.

        On the one hand, the specification says that the dl capability should
        delete ``n`` number of lines, on the other hand, in the reality, dl
        just scrolls up ``n`` number of lines. Notice, that dl should work
        together with another capability that will put the cursor on the
        line that is going to be deleted. For example, in tests dl works
        together with the home capability, but it doesn't mean that the
        capabilities are always used together.
        """
        if self._top_most <= self._cur_y <= self._bottom_most:
            for _ in range(n):
                self._scroll_up(self._cur_y + 1, self._bottom_most)

    def _cap_dl1(self):
        """Delete a line."""
        self._cap_dl(1)

    def _cap_ech(self, n):
        """Erase ``n`` number of characters."""
        self._zero((self._cur_x, self._cur_y), (self._cur_x + n, self._cur_y),
                   inclusively=True)

    def _cap_ed(self):
        """Clear the screen from the current cursor position to the end of the
        screen.
        """
        self._zero((self._cur_x, self._cur_y), (self._cols, self._rows - 1))

    def _cap_el(self):
        """Clear a line from the current cursor position to the end of the
        line without moving the cursor. See _cap_el1.
        """
        self._zero((self._cur_x, self._cur_y), (self._cols, self._cur_y))

    def _cap_el1(self):
        """Clear a line from the beginning to the current cursor position,
        inclusive. The cursor is not moved. See _cap_el.
        """
        self._zero((0, self._cur_y), (self._cur_x, self._cur_y),
                   inclusively=True)

    def _cap_home(self):
        """Move the cursor to the home position."""
        self._cur_x = 0
        self._cur_y = 0
        self._eol = False

    def _cap_ht(self):
        """Tab to the next 8-space hardware tab stop."""
        x = self._cur_x + 8
        q, _ = divmod(x, 8)
        self._cur_x = (q * 8) % self._cols

    def _cap_ich(self, n):
        """Insert ``n`` number of blank characters."""
        for i in range(n):
            self._scroll_right(self._cur_x + i, self._cur_y)

    def _cap_il(self, n):
        """Add ``n`` number of new blank lines."""
        for _ in range(n):
            if self._cur_y < self._bottom_most:
                self._scroll_down(self._cur_y, self._bottom_most)

    def _cap_il1(self):
        """Add a new blank line."""
        self._cap_il(1)

    def _cap_kb2(self):
        """Handle a Center key-press on keypad."""
        # xterm and Linux console have the kb2 capability, but screen doesn't.
        # Some terminal emulators even handle it in spite of the seeming
        # uselessness of the capability.
        # It's been decided to have a do-nothing handler for kb2.

    def _cap_kcub1(self):
        """Handle a Left Arrow key-press."""
        self._cur_x = max(0, self._cur_x - 1)
        self._eol = False

    def _cap_kcud1(self):
        """Handle a Down Arrow key-press."""
        self._cap_cud(1)

    def _cap_kcuf1(self):
        """Handle a Right Arrow key-press."""
        self._cap_cuf(1)

    def _cap_kcuu1(self):
        """Handle an Up Arrow key-press."""
        self._cur_y = max(self._top_most, self._cur_y - 1)

    def _cap_rc(self):
        """Restore the cursor to the last saved position. See _cap_sc."""
        self._cur_x = self._cur_x_bak
        self._cur_y = self._cur_y_bak
        self._eol = self._cur_x == self._right_most

    def _cap_rmir(self):
        """Exit Insert mode. See _cap_smir."""

    def _cap_sc(self):
        """Save the current cursor position. See _cap_rc."""
        self._cur_x_bak = self._cur_x
        self._cur_y_bak = self._cur_y

    def _cap_smir(self):
        """Enter Insert mode. See _cap_rmir."""

    def _cap_vpa(self, y):
        """Set the vertical position of the cursor to ``y``. See _cap_hpa.

        The ``y`` value starts from 1.
        """
        self._cur_y = min(self._bottom_most, y - 1)

    def _cap_hpa(self, x):
        """Set the horizontal position of the cursor to ``x``. See _cap_vpa.

        The ``x`` value starts from 1.
        """
        self._cur_x = min(self._right_most, x - 1)
        self._eol = False  # it's necessary to reset _eol after preceding echo

    def _build_html(self):  # noqa: C901
        """Transform the internal representation of the screen into the HTML
        representation.
        """
        self._clean_bit(REVERSE_BIT)

        rows = self._rows
        cols = self._cols
        r = ''

        span = ''  # ready-to-output characters
        span_classes = []
        for i in range(rows * cols):
            cell = self._screen[i]
            q, c = divmod(cell, MAGIC_NUMBER)
            bg, fg = divmod(q, 16)

            current_classes = [
                f'b{bg}',
                f'f{fg}',
            ]

            if self._is_bit_set(UNDERLINE_BIT, cell):
                current_classes.append('underline')

            if self._is_bit_set(REVERSE_BIT, cell):
                current_classes[0] = f'b{fg}'
                current_classes[1] = f'f{bg}'

            if self._is_bit_set(BLINK_BIT, cell):
                current_classes.append('blink')

            if self._is_bit_set(BOLD_BIT, cell):
                current_classes.append('bold')

            if i == self._cur_y * cols + self._cur_x and self._cur_visible:
                current_classes[0], current_classes[1] = 'b1', 'f7'  # cursor

            # If the characteristics of the current cell match the
            # characteristics of the previous cell, combine them into a group.
            if span_classes != current_classes or i + 1 == rows * cols:
                if span:
                    classes = ' '.join(span_classes)
                    # Replace spaces with non-breaking spaces.
                    ch = html.escape(span.replace(' ', '\xa0'))
                    r += f'<span class="{classes}">{ch}</span>'
                span = ''
                span_classes = current_classes.copy()

            if c == 0:
                span += ' '

            span += chr(c & 0xFFFF)

            if not (i + 1) % cols:
                span += '\n'

        return r

    #
    # User visible methods.
    #
    def generate_html(self, buf):
        """Split ``buf`` into output, escape and control sequences. The output
        prints on the screen as is. The escape and control sequences are
        executed, affecting the output. Finally, the routine generates the HTML
        document which is ready to be printed in a user's browser.

        The ``buf`` argument is a byte buffer taken from a terminal-oriented
        program.
        """
        for i in buf.decode('utf8', errors='replace'):
            if ord(i) in self.control_characters:
                self._buf = i
                self._exec_single_character_command()
            elif i == '\x1b':
                self._buf += i
            elif len(self._buf):
                self._buf += i
                self._exec_escape_sequence()
            else:
                self._echo(i)

        return self._build_html()
