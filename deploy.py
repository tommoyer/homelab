from __future__ import annotations

from homelab import deploy as _deploy


def main(argv: list[str] | None = None) -> int:
    return int(_deploy.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
