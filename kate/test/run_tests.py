"""The module runs all the tests."""

# ruff: noqa: F401

import unittest

from kate.test.test_mixins.test_absolute_positioning import AbsolutePositioningTest
from kate.test.test_mixins.test_arrow_key_handling import ArrowKeyHandlingMixinTest
from kate.test.test_mixins.test_basic_cursor_movements import BasicCursorMovementTest
from kate.test.test_mixins.test_character_operations import CharacterOperationsTest
from kate.test.test_mixins.test_cursor_state import CursorStateTest
from kate.test.test_mixins.test_line_operations import LineOperationsTest
from kate.test.test_mixins.test_screen_buffer import ScreenBufferTest

if __name__ == '__main__':
    unittest.main()
