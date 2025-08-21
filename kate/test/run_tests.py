"""The module runs all the tests."""

# ruff: noqa: F401

import unittest

from kate.test.capabilities_test import TestCapabilities
from kate.test.core.test_escape import TestEscapeFunctions
from kate.test.core.test_httputil import TestHTTPUtilityFunctions
from kate.test.core.test_server import TestBaseServer, TestResponse
from kate.test.core.test_util import TestWebSocketMaskPython
from kate.test.core.test_websocket_handler import (
    TestPerMessageDeflateCompressor,
    TestPerMessageDeflateDecompressor,
    TestPerMessageDeflateDefaults,
    TestWebSocketHandler,
)
from kate.test.core.test_websocket_protocol13 import (
    TestWebSocketProtocol13CompressionHelpers,
    TestWebSocketProtocol13Handshake,
    TestWebSocketProtocol13PeriodicPing,
    TestWebSocketProtocol13Reading,
    TestWebSocketProtocol13TimersAndSocket,
    TestWebSocketProtocol13Writing,
    TestWebSocketProtocolBase,
)

if __name__ == '__main__':
    unittest.main()
