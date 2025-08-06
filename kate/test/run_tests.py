"""The module runs all the tests."""

# ruff: noqa: F401

import unittest

from kate.test.test_mixins.test_absolute_positioning import AbsolutePositioningTest
from kate.test.test_mixins.test_arrow_key_handling import ArrowKeyHandlingMixinTest

if __name__ == '__main__':
    unittest.main()
