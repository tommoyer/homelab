#!/usr/bin/env python3

from __future__ import annotations

from homelab import ui as _ui


def main(argv: list[str] | None = None) -> int:
    return int(_ui.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
