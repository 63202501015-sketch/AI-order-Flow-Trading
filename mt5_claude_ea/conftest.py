import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for p in (_HERE, _HERE / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
