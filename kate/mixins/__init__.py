"""The package contains the mixins to extend a terminal possibilities."""

from kate.mixins.absolute_positioning import AbsolutePositioningMixin
from kate.mixins.arrow_key_handling import ArrowKeyHandlingMixin
from kate.mixins.basic_cursor_movement import BasicCursorMovementMixin
from kate.mixins.bit_flags import BitFlagsMixin
from kate.mixins.character_operations import CharacterOperationsMixin
from kate.mixins.color_managment import ColorManagementMixin
from kate.mixins.cursor_state import CursorStateMixin
from kate.mixins.execution import ExecutionMixin
from kate.mixins.insert_mode import InsertModeMixin
from kate.mixins.line_operations import LineOperationsMixin
from kate.mixins.screen_buffer import ScreenBufferMixin
from kate.mixins.screen_clearing import ScreenClearingMixin
from kate.mixins.scrolling_control import ScrollingControlMixin
from kate.mixins.text_attributes import TextAttributesMixin

__all__ = (
    'AbsolutePositioningMixin',
    'ArrowKeyHandlingMixin',
    'BasicCursorMovementMixin',
    'BitFlagsMixin',
    'CharacterOperationsMixin',
    'ColorManagementMixin',
    'CursorStateMixin',
    'ExecutionMixin',
    'InsertModeMixin',
    'LineOperationsMixin',
    'ScreenBufferMixin',
    'ScreenClearingMixin',
    'ScrollingControlMixin',
    'TextAttributesMixin',
)
