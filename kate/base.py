"""The module contains base implementation of the Terminal."""

import array
import logging
import re
from pathlib import Path

import yaml

from kate.constants import BLACK_AND_WHITE


class BaseTerminal:
    """The class represents base implementation of the Terminal."""

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
            Path(__file__).parent / 'linux_console.yml',
        ).read_text(encoding='utf-8')
        sequences = yaml.load(linux_console, Loader=yaml.SafeLoader)

        self.control_characters = sequences['control_characters']

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

    def _cap_rs1(self):
        """Reset terminal completely to sane modes."""
        cells_number = self._cols * self._rows
        self._screen = array.array('Q', [BLACK_AND_WHITE] * cells_number)
        self._sgr = BLACK_AND_WHITE
        self._cur_x_bak = self._cur_x = 0
        self._cur_y_bak = self._cur_y = 0
        self._eol = False
        self._left_most = self._top_most = 0
        self._bottom_most = self._rows - 1
        self._right_most = self._cols - 1

        self._buf = ''
        self._outbuf = ''
