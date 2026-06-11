"""Shared pytest fixtures and module stubs for the test suite.

Heavy optional dependencies (faster_whisper, etc.) are stubbed so that
app.handlers can be imported without requiring GPU/ML packages.
"""

import sys
from unittest.mock import MagicMock

# Stub faster_whisper before any app module is imported.
if "faster_whisper" not in sys.modules:
    sys.modules["faster_whisper"] = MagicMock()
