"""The module contains base classes and utils used in core package."""

import socket
import unittest
from unittest.mock import AsyncMock, Mock

from kate.core.websocket import (
    WebSocketHandler,
    WebSocketProtocol13,
    _default_max_message_size,
    _WebSocketParams,
)


def get_default_headers():
    """Return default headers."""
    return {
        'Host': 'example.com',
        'Origin': 'http://example.com',
        'Upgrade': 'websocket',
        'Connection': 'Upgrade',
        'Sec-WebSocket-Version': '13',
        'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ==',
    }


def get_params(**kwargs):
    """Return default WebSocket parameters."""
    return _WebSocketParams(
        ping_interval=kwargs.get('ping_interval'),
        ping_timeout=kwargs.get('ping_timeout'),
        max_message_size=kwargs.get('max_message_size', _default_max_message_size),
        compression_options=kwargs.get('compression_options'),
    )


def get_writer():
    """Return a stream writer."""
    writer = Mock()
    writer.write = Mock()
    writer.drain = AsyncMock()
    writer.close = Mock()
    writer.wait_closed = AsyncMock()
    writer.is_closing = Mock(return_value=False)
    return writer


class BaseWebSocketTestCase(unittest.IsolatedAsyncioTestCase):
    """Base test class to set up common test fixtures for WebSocket tests."""

    def setUp(self):
        """Set up the test environment."""
        self.reader = AsyncMock()
        self.writer = get_writer()
        self.server = DummyServer()
        self.headers = get_default_headers()
        self.handler = WebSocketHandler(self.headers, self.reader, self.writer, self.server)
        self.handler.open_args = ()
        self.handler.open_kwargs = {}
        self.protocol = WebSocketProtocol13(
            self.handler,
            mask_outgoing=False,
            params=get_params(),
            reader=self.reader,
            writer=self.writer,
        )


class DummyServer:
    """The class represents a minimal server stub exposing send_http_error
    and the socket attribute.
    """

    def __init__(self, *, with_socket=False):
        """Initialize a DummyServer object."""
        self.send_http_error = AsyncMock()
        self.socket = None

        if with_socket:
            sock = Mock()
            sock.family = socket.AF_INET
            sock.setsockopt = Mock()
            self.socket = sock
