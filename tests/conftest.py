"""
Test configuration and fixtures.

Tests run without Django; netbox module is mocked to avoid import errors.
"""
import sys
from unittest.mock import MagicMock

# Mock netbox module before importing netbox_bmc
sys.modules["netbox"] = MagicMock()
sys.modules["netbox.plugins"] = MagicMock()

# Mock dcim module for lazy imports in tests
sys.modules["dcim"] = MagicMock()
sys.modules["dcim.models"] = MagicMock()
sys.modules["dcim.models.modules"] = MagicMock()
