from __future__ import annotations

from homelab import pihole as _pihole


def main(argv: list[str] | None = None) -> int:
    return int(_pihole.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
