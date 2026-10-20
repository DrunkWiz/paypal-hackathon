"""Root conftest: make the repo root importable so `import contracts` works
regardless of pytest's rootdir/insertion heuristics.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
