"""The module contains mixin for executing or ignoring control sequences."""

from kate.base import BaseTerminal


class ExecutionMixin(BaseTerminal):
    """The mixin contains methods for executing or ignoring control sequences."""

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
