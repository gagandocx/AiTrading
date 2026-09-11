"""Make `src/` importable without requiring an install.

The package lives under src/ (a src-layout), so `import aitrading` fails from a
clean checkout unless the path is set up. pytest imports this file automatically
before collecting tests, which makes `pytest tests/` work with no PYTHONPATH and
no `pip install -e .`.

Kept at the repository root deliberately: pytest walks upward from the test
directory looking for conftest.py, so this applies to every test module.
"""

import sys
from pathlib import Path

SRC = Path(__file__).parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
