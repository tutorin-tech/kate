"""The package contains mixins for extending the terminal functionality."""

from kate.mixins.content import ContentMixin
from kate.mixins.core import CoreMixin
from kate.mixins.cursor import CursorMixin
from kate.mixins.screen_buffer import ScreenBufferMixin
from kate.mixins.visual_attributes import VisualAttributesMixin

__all__ = (
    'ContentMixin',
    'CoreMixin',
    'CursorMixin',
    'ScreenBufferMixin',
    'VisualAttributesMixin',
)
