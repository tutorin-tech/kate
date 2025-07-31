"""The module runs all the tests."""

# ruff: noqa: F401

import unittest

from tests.terminal_test import TerminalTest
from tests.test_mixins.test_absolute_positioning import AbsolutePositioningTest
from tests.test_mixins.test_arrow_key_handling import ArrowKeyHandlingMixinTest
from tests.test_mixins.test_basic_cursor_movements import BasicCursorMovementTest
from tests.test_mixins.test_character_operations import CharacterOperationsTest
from tests.test_mixins.test_cursor_state import CursorStateTest
from tests.test_mixins.test_line_operations import LineOperationsTest
from tests.test_mixins.test_screen_buffer import ScreenBufferTest
from tests.test_mixins.test_screen_clearing import ScreenClearingTest
from tests.test_mixins.test_scrolling_control import ScrollingControlTest
from tests.test_mixins.test_text_attributes import TextAttributesTest

if __name__ == '__main__':
    unittest.main()
