"""Put the import roots on the path once, rather than in every test module.

`tools/` is separate because demangle.py is a standalone script that lives
there and is imported directly by its tests.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (ROOT, os.path.join(ROOT, "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)
