from __future__ import annotations

from homelab import caddyfile as _caddyfile


def main(argv: list[str] | None = None) -> int:
    return int(_caddyfile.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
