"""The module contains mixin related to color management."""

# ruff: noqa: PLR2004

from kate.constants import BLACK_AND_WHITE, BOLD_BIT, MAGIC_NUMBER


class ColorManagementMixin:
    """The mixin contains methods related to color management."""

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
