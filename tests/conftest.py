"""Put the import roots on the path once, rather than in every test module.

`tools/` is separate because demangle.py is a standalone script that lives
there and is imported directly by its tests.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (ROOT, os.path.join(ROOT, "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture(scope="session")
def library():
    """Parsed once for the whole run: it walks the music folder and reads the
    library XML."""
    from build_browser import read_library
    return read_library()
