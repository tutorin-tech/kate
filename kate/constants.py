"""The module contains constants."""

MAGIC_NUMBER = 0x10000000000
# +------------------+--------------------------------------------------------+
# | character (0-31) | 4-byte value represents a character in UTF-8 encoding. |
# +------------------+--------------------------------------------------------+
# | emphasis and     | 1-byte value represents 8 emphasis and modes. Each of  |
# | modes (32-39)    | them is represented by 1 bit.                          |
# |                  | 32) underline                                          |
# |                  | 33) reverse                                            |
# |                  | 34) blink                                              |
# |                  | 35) dim                                                |
# |                  | 36) bold                                               |
# |                  | 37) blank                                              |
# |                  | 38) protect                                            |
# |                  | 39) alternate character set                            |
# +------------------+--------------------------------------------------------+
# | colors (40-46)   | 7-bit value represents both background and foreground  |
# |                  | color. To get them divide the value by 16 via divmod.  |
# |                  | The result will be a tuple (bg, fg).                   |
# +------------------+--------------------------------------------------------+

# The colors section of MAGIC_NUMBER stores 7, i.e. (0, 7) or black and white.
BLACK_AND_WHITE = MAGIC_NUMBER * 7

UNDERLINE_BIT = 32
REVERSE_BIT = 33
BLINK_BIT = 34
BOLD_BIT = 36
