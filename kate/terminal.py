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

# ruff: noqa: PLR2004

import html

from kate import mixins
from kate.base import BaseTerminal
from kate.constants import (
    BLACK_AND_WHITE,
    BLINK_BIT,
    BOLD_BIT,
    MAGIC_NUMBER,
    REVERSE_BIT,
    UNDERLINE_BIT,
)


class Terminal(
    mixins.BitFlagsMixin,
    mixins.ScreenBufferMixin,
    BaseTerminal,
):
    """The class implements a terminal."""

    #
    # Internal methods.
    #

    def _exec_method(self, name, args=None):
        """Try to find the specified method and, in case the try succeeds,
        executes it.

        The ``name`` argument is a name of the target method. First,
        `_exec_method` tries to find _cap_``name``, then _``name``.
        The ``args`` argument must be a list of arguments to be passed to the
        target method.
        """
        if args is None:
            args = []

        method = (getattr(self, '_cap_' + name, None) or
                  getattr(self, '_' + name, None))
        if method:
            method(*args)
        else:
            self._logger.fatal('The _cap_%s and _%s methods do not exist', name, name)

    def _ignore(self):
        """Allow ignoring some escape and control sequences."""

    def _default_rendition(self):
        """Cancel the effect of any preceding occurrence of SGR in the data
        stream regardless of the setting of the GRAPHIC RENDITION COMBINATION
        MODE (GRCM). For details, see section 8.3.117, "SGR - SELECT GRAPHIC
        RENDITION," in ECMA-048 at
        http://www.ecma-international.org/publications/standards/Ecma-048.htm.
        """
        self._set_color(0)

    def _set_bg_color(self, color):
        """Set the background color."""
        color_bits, _ = divmod(self._sgr, MAGIC_NUMBER)
        _, fg = divmod(color_bits, 16)
        new_color_bits = color * 16 + fg
        self._sgr &= ~(color_bits << 40)  # clear color bits
        self._sgr |= new_color_bits << 40  # update bg and fg colors

    def _set_fg_color(self, color):
        """Set the foreground color."""
        color_bits, _ = divmod(self._sgr, MAGIC_NUMBER)
        bg, _ = divmod(color_bits, 16)

        # bold also means extra bright, so if the corresponding bit is set, we
        # have to switch to the bright color scheme.
        if self._sgr & (1 << BOLD_BIT):
            color += 8

        new_color_bits = bg * 16 + color
        self._sgr &= ~(color_bits << 40)  # clear color bits
        self._sgr |= new_color_bits << 40  # update bg and fg colors

    def _set_color_pair(self, p1, p2):
        if (p1 == 0 and p2 == 10) or (p1 == 39 and p2 == 49):  # sgr0
            self._sgr = BLACK_AND_WHITE
        else:
            self._set_attribute(p1)
            self._set_color(p2)

    def _set_attribute(self, p1):
        """Set attribute parameters of SGR."""
        if p1 == 1:
            self._cap_bold()
        elif p1 == 2:
            self._cap_dim()
        elif p1 == 4:
            self._cap_smul()
        elif p1 == 5:
            self._cap_blink()
        elif p1 == 7:
            self._cap_rev()
        elif p1 == 10:
            self._cap_rmpch()
        elif p1 == 11:
            self._cap_smpch()
        elif p1 == 24:
            self._cap_rmul()
        elif p1 == 27:
            self._cap_rmso()

    def _set_color(self, color):
        if color == 0:
            self._sgr = BLACK_AND_WHITE
        elif 30 <= color <= 37:  # setaf
            self._set_fg_color(color - 30)
        elif color == 39:
            self._sgr = BLACK_AND_WHITE
        elif 40 <= color <= 47:  # setab
            self._set_bg_color(color - 40)
        elif color == 49:
            self._sgr = BLACK_AND_WHITE

    def _cap_blink(self):
        """Produce blinking text."""
        self._set_bit(BLINK_BIT)

    def _cap_bold(self):
        """Produce bold text."""
        self._set_bit(BOLD_BIT)
        self._set_color(37)

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

    def _cap_dim(self):
        """Enter Half-bright mode."""

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

    def _cap_op(self):
        """Set default color-pair to the original one. The name of the
        capability stands for 'original pair'.
        """
        self._set_color_pair(39, 49)

    def _cap_rc(self):
        """Restore the cursor to the last saved position. See _cap_sc."""
        self._cur_x = self._cur_x_bak
        self._cur_y = self._cur_y_bak
        self._eol = self._cur_x == self._right_most

    def _cap_rev(self):
        """Enable Reverse Video mode."""
        self._set_bit(REVERSE_BIT)

    def _cap_rmir(self):
        """Exit Insert mode. See _cap_smir."""

    def _cap_rmpch(self):
        """Exit PC character display mode. See _cap_smpch."""

    def _cap_rmso(self):
        """Exit Standout mode. See _cap_smso."""

    def _cap_rmul(self):
        """Exit Underline mode. See _cap_smul."""
        self._clean_bit(UNDERLINE_BIT)

    def _cap_sc(self):
        """Save the current cursor position. See _cap_rc."""
        self._cur_x_bak = self._cur_x
        self._cur_y_bak = self._cur_y

    def _cap_sgr(self, p1=0, p2=0, p3=0, p4=0, p5=0, p6=0, p7=0, p8=0, p9=0):
        """Allow setting arbitrary combinations of modes taking nine
        arguments. The nine arguments are, in order:
        * standout;
        * underline;
        * reverse;
        * blink;
        * dim;
        * bold;
        * blank;
        * protect;
        * alternate character set.
        """

    def _cap_sgr0(self):
        """Reset all attributes to the default values."""
        self._set_color_pair(0, 10)

    def _cap_smir(self):
        """Enter Insert mode. See _cap_rmir."""

    def _cap_smso(self):
        """Enter Standout mode. See _cap_rmso.

        John Strang, in his book Programming with Curses, gives the following
        definition for the term. Standout mode is whatever special highlighting
        the terminal can do, as defined in the terminal's database entry.
        """

    def _cap_smul(self):
        """Enter Underline mode. See _cap_rmul."""
        self._set_bit(UNDERLINE_BIT)

    def _cap_smpch(self):
        """Enter PC character display mode. See _cap_rmpch."""

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

    def _exec_escape_sequence(self):
        r"""Match either static escape sequences (such as \E[1m and \E[0;10m)
        or escape sequences with parameters (such as \E[%d@ and \E[%d;%dr) to
        one of the capabilities from the files, containing the matching rules
        (escape sequence to capability). Then the capabilities are executed.
        """
        method_name = self._escape_sequences.get(self._buf, None)

        if len(self._buf) > 32:
            self._buf = ''
        elif method_name:  # static sequences
            self._exec_method(method_name)
            self._buf = ''
        else:  # sequences with params
            for sequence, capability in self._escape_sequences_re:
                mo = sequence.match(self._buf)
                if mo:
                    args = [int(i) for i in mo.groups()]

                    self._exec_method(capability, args)
                    self._buf = ''

    def _exec_single_character_command(self):
        """Execute control sequences like 10 (LF, line feed) or 13 (CR,
        carriage return).
        """
        method_name = self.control_characters[ord(self._buf)]
        self._exec_method(method_name)
        self._buf = ''

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
