"""The module runs all the tests."""

# ruff: noqa: F401

import unittest

from kate.test.capabilities_test import TestCapabilities
from kate.test.core.original_websocket_tests import (
    CompressionTests,
    MaxMessageSizeTest,
    PingTests,
    WebSocketNativeCoroutineTest,
    WebSocketTest,
)
from kate.test.core.test_escape import TestCoreEscape
from kate.test.core.test_httputil import TestCoreHTTPUtility
from kate.test.core.test_server import TestResponse, TestServer
from kate.test.core.test_util import TestPythonMaskFunction
from kate.test.core.test_websocket_handler import TestWebSocketHandler
from kate.test.core.test_websocket_protocol13 import (
    TestWebSocketProtocol13Close,
    TestWebSocketProtocol13Compression,
    TestWebSocketProtocol13Handshake,
    TestWebSocketProtocol13PeriodicPinging,
    TestWebSocketProtocol13Reading,
    TestWebSocketProtocol13Writing,
    TestWebSocketProtocolBase,
)

if __name__ == '__main__':
    unittest.main()
