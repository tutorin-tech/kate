"""Test mixins for terminal capabilities."""

from tests.mixins.test_content_mixin import TestContentMixin
from tests.mixins.test_cursor_mixin import TestCursorMixin
from tests.mixins.test_screen_buffer_mixin import TestScreenBufferMixin
from tests.mixins.test_visual_attributes_mixin import TestVisualAttributesMixin

__all__ = (
    'TestContentMixin',
    'TestCursorMixin',
    'TestScreenBufferMixin',
    'TestVisualAttributesMixin',
)
