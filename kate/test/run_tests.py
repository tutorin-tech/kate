"""The module runs all the tests."""

# ruff: noqa: F401

import unittest

from kate.test.capabilities_test import TestCapabilities
from kate.test.core.test_server import TestBaseServer
from kate.test.core.websocket.test_escape import TestEscapeFunctions
from kate.test.core.websocket.test_httputil import (
    TestABNFPatterns,
    TestHTTPHeaders,
    TestHTTPUtilityFunctions,
    TestRequestStartLine,
    TestResponseStartLine,
)
from kate.test.core.websocket.test_protocol import TestWebSocketProtocol13
from kate.test.core.websocket.test_websocket_handler import TestWebSocketHandler

if __name__ == '__main__':
    unittest.main()
