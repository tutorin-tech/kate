"""The module runs all the tests."""

# ruff: noqa: F401

import unittest

from kate.tests.capabilities_test import TestCapabilities
from kate.tests.core.original_websocket_tests import (
    CompressionTests,
    MaxMessageSizeTest,
    PingTests,
    WebSocketNativeCoroutineTest,
    WebSocketTest,
)
from kate.tests.core.test_escape import TestCoreEscape
from kate.tests.core.test_httputil import TestCoreHTTPUtility
from kate.tests.core.test_server import TestResponse, TestServer
from kate.tests.core.test_util import TestPythonMaskFunction
from kate.tests.core.test_websocket_handler import TestWebSocketHandler
from kate.tests.core.test_websocket_protocol13 import (
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
