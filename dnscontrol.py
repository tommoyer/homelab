from __future__ import annotations

from homelab import dnscontrol as _dnscontrol


def main(argv: list[str] | None = None) -> int:
    return int(_dnscontrol.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
