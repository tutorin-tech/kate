"""The module contains exceptions used for server implementation."""


class WebSocketError(Exception):
    """The class represents a base class for exceptions related to websocket."""


class WebSocketClosedError(WebSocketError):
    """Raised by operations on a closed connection."""


class _DecompressTooLargeError(Exception):
    """Raised when message to decompress is too big."""
