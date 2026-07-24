"""Shared pytest fixtures and module stubs for the test suite.

Heavy optional dependencies (faster_whisper, etc.) are stubbed so that
app.handlers can be imported without requiring GPU/ML packages.
"""

import sys
from unittest.mock import MagicMock

# Stub heavy optional dependencies before any app module is imported.
if "faster_whisper" not in sys.modules:
    sys.modules["faster_whisper"] = MagicMock()

# Stub CalDAV dependencies — not installed locally, only in Docker.
for _mod in ("caldav", "icalendar"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
