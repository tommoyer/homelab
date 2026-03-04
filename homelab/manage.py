#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script (e.g. `python3 homelab/manage.py`) by ensuring the
# repo root is on sys.path so `import homelab` resolves.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from homelab.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
