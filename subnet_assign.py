from __future__ import annotations

from homelab import subnet_assign as _subnet_assign


def main(argv: list[str] | None = None) -> int:
    return int(_subnet_assign.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
