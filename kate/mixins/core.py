"""The module provides a core mixin."""

import array

from kate.constants import BLACK_AND_WHITE


class CoreMixin:
    """The mixin provides the core functionality needed for terminal operations."""

    def _clean_bit(self, bit):
        """Clean the specified `_sgr` bit."""
        self._sgr &= ~(1 << bit)

    @staticmethod
    def _is_bit_set(bit, value):
        """Check if the specified bit is set in the specified value."""
        return bool(value & (1 << bit))

    def _set_bit(self, bit):
        """Set the specified `_sgr` bit."""
        self._sgr |= 1 << bit

    def _exec_escape_sequence(self):
        r"""Match either static escape sequences (such as \E[1m and \E[0;10m)
        or escape sequences with parameters (such as \E[%d@ and \E[%d;%dr) to
        one of the capabilities from the files, containing the matching rules
        (escape sequence to capability). Then the capabilities are executed.
        """
        method_name = self._escape_sequences.get(self._buf, None)

        if len(self._buf) > 32:  # noqa: PLR2004
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

    def _exec_single_character_command(self):
        """Execute control sequences like 10 (LF, line feed) or 13 (CR,
        carriage return).
        """
        method_name = self.control_characters[ord(self._buf)]
        self._exec_method(method_name)
        self._buf = ''

    def _ignore(self):
        """Allow ignoring some escape and control sequences."""

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
