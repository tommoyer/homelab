from __future__ import annotations

from homelab import mikrotik_prompt


def main(argv: list[str] | None = None) -> int:
    return int(mikrotik_prompt.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
