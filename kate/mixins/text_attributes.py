"""The module contains mixin related to text styling, colors, and attributes."""

# ruff: noqa: PLR2004

from kate.base import BaseTerminal
from kate.constants import (
    BLACK_AND_WHITE,
    BLINK_BIT,
    BOLD_BIT,
    MAGIC_NUMBER,
    REVERSE_BIT,
    UNDERLINE_BIT,
)


class TextAttributesMixin(BaseTerminal):
    """The mixin contains methods related to text styling, colors, and attributes.

    Note: Mind the inheriting order since this mixin requires methods
    from BitFlagsMixin.
    """

    def _default_rendition(self):
        """Cancel the effect of any preceding occurrence of SGR in the data
        stream regardless of the setting of the GRAPHIC RENDITION COMBINATION
        MODE (GRCM). For details, see section 8.3.117, "SGR - SELECT GRAPHIC
        RENDITION," in ECMA-048 at
        http://www.ecma-international.org/publications/standards/Ecma-048.htm.
        """
        self._set_color(0)

    def _cap_blink(self):
        """Produce blinking text."""
        self._set_bit(BLINK_BIT)

    def _cap_bold(self):
        """Produce bold text."""
        self._set_bit(BOLD_BIT)
        self._set_color(37)

    def _cap_dim(self):
        """Enter Half-bright mode."""

    def _cap_op(self):
        """Set default color-pair to the original one. The name of the
        capability stands for 'original pair'.
        """
        self._set_color_pair(39, 49)

    def _cap_rev(self):
        """Enable Reverse Video mode."""
        self._set_bit(REVERSE_BIT)

    def _cap_rmpch(self):
        """Exit PC character display mode. See _cap_smpch."""

    def _cap_rmso(self):
        """Exit Standout mode. See _cap_smso."""

    def _cap_rmul(self):
        """Exit Underline mode. See _cap_smul."""
        self._clean_bit(UNDERLINE_BIT)

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

    def _cap_smpch(self):
        """Enter PC character display mode. See _cap_rmpch."""

    def _cap_smso(self):
        """Enter Standout mode. See _cap_rmso.

        John Strang, in his book Programming with Curses, gives the following
        definition for the term. Standout mode is whatever special highlighting
        the terminal can do, as defined in the terminal's database entry.
        """

    def _cap_smul(self):
        """Enter Underline mode. See _cap_rmul."""
        self._set_bit(UNDERLINE_BIT)

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

    def _set_bg_color(self, color):
        """Set the background color."""
        color_bits, _ = divmod(self._sgr, MAGIC_NUMBER)
        _, fg = divmod(color_bits, 16)
        new_color_bits = color * 16 + fg
        self._sgr &= ~(color_bits << 40)  # clear color bits
        self._sgr |= new_color_bits << 40  # update bg and fg colors

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

    def _set_color_pair(self, p1, p2):
        if (p1 == 0 and p2 == 10) or (p1 == 39 and p2 == 49):  # sgr0
            self._sgr = BLACK_AND_WHITE
        else:
            self._set_attribute(p1)
            self._set_color(p2)

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
