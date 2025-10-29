"""The module runs all the tests."""

# ruff: noqa: F401

import unittest

from tests.capabilities_test import TestCapabilities
from tests.core.original_websocket_tests import (
    CompressionTests,
    MaxMessageSizeTest,
    PingTests,
    WebSocketNativeCoroutineTest,
    WebSocketTest,
)
from tests.core.test_escape import TestCoreEscape
from tests.core.test_httputil import TestCoreHTTPUtility
from tests.core.test_server import TestResponse, TestServer
from tests.core.test_util import TestPythonMaskFunction
from tests.core.test_websocket_handler import TestWebSocketHandler
from tests.core.test_websocket_protocol13 import (
    TestWebSocketProtocol13Close,
    TestWebSocketProtocol13Compression,
    TestWebSocketProtocol13Handshake,
    TestWebSocketProtocol13PeriodicPinging,
    TestWebSocketProtocol13Reading,
    TestWebSocketProtocol13Writing,
    TestWebSocketProtocolBase,
)
from tests.mixins import (
    TestContentMixin,
)

if __name__ == '__main__':
    unittest.main()
