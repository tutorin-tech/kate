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
import json
import logging
import re
from pathlib import Path

from kate import mixins
from kate.constants import (
    BLINK_BIT,
    BOLD_BIT,
    MAGIC_NUMBER,
    REVERSE_BIT,
    UNDERLINE_BIT,
)


class Terminal(
    mixins.ContentMixin,
    mixins.CoreMixin,
    mixins.CursorMixin,
    mixins.ScreenBufferMixin,
    mixins.VisualAttributesMixin,
):
    """The class implements a terminal."""

    def __init__(self, rows=24, cols=80):
        """Initialize a Terminal object."""
        self._cols = cols
        self._rows = rows
        self._cur_y = None
        self._cur_x = None
        self._cur_visible = True

        # The following two fields are used only for implementation of
        # storing (sc) and restoring (rc) the current cursor position.
        self._cur_x_bak = 0
        self._cur_y_bak = 0

        self._screen = None

        # eol stands for 'end of line' and is set to True when the cursor
        # reaches the right side of the screen.
        self._eol = False

        # The following fields allow abstracting from the rows and cols
        # concept.
        self._top_most = None
        self._bottom_most = None
        self._left_most = None
        self._right_most = None

        self._sgr = None  # Select Graphic Rendition

        # Kate supports two color schemes: normal and bright. Each color scheme
        # consists of 8 colors for a background and text. The terminal doesn't
        # allow users to switch between them so far.
        # The bright color scheme is used by default.
        self._normal_mode = False

        self._logger = logging.getLogger('tornado.application')

        self._buf = ''
        self._outbuf = ''

        linux_console = Path(
            Path(__file__).parent / 'linux_console.json',
        ).read_text(encoding='utf-8')
        linux_console = re.sub(r'//.*', '', linux_console)  # remove comments
        sequences = json.loads(linux_console)

        self.control_characters = {int(k): v for k, v in sequences['control_characters'].items()}

        self._escape_sequences = {}
        for k, v in sequences['escape_sequences'].items():
            self._escape_sequences[k.replace('\\E', '\x1b')] = v

        self._escape_sequences_re = []
        for k, v in sequences['escape_sequences_re'].items():
            sequence = k.replace(
                '\\E', '\x1b',
            ).replace(
                '[', r'\[',
            ).replace(
                '%d', '([0-9]+)',
            )

            self._escape_sequences_re.append(
                (re.compile(sequence), v),
            )

        self._cap_rs1()

    #
    # Internal methods.
    #

    def _echo(self, c):
        """Put the specified character ``c`` on the screen and moves the
        cursor right by 1 position. If the cursor reaches the end of a line,
        it is moved to the next line.
        """
        if self._eol:
            self._cursor_down()
            self._cur_x = 0

        pos = self._cur_y * self._cols + self._cur_x
        self._screen[pos] = self._sgr | ord(c)
        self._cursor_right()

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
