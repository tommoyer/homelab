"""Shared FQDN/zone utilities used by dns.py and caddyfile.py."""

from __future__ import annotations

import sys
from typing import Any

from .sheets import as_str

EXPOSURE_PUBLIC = "public"
EXPOSURE_PRIVATE = "private"
EXPOSURE_LOCAL = "local"
EXPOSURE_TRUSTED = "trusted"

_EXPOSURE_ALIASES = {
    "tailnet-only": EXPOSURE_TRUSTED,
    "non-public": EXPOSURE_TRUSTED,
}

ALLOWED_EXPOSURES_DNS = {EXPOSURE_PUBLIC, EXPOSURE_PRIVATE, EXPOSURE_LOCAL}
ALLOWED_EXPOSURES_CADDY = {EXPOSURE_PUBLIC, EXPOSURE_TRUSTED}


def determine_zone(hostname: str, zones: list[str]) -> str | None:
    target = hostname.lower().rstrip(".")
    matches = [z for z in zones if target == z or target.endswith(f".{z}")]
    return max(matches, key=len) if matches else None


def normalize_exposure(
    value: Any,
    *,
    strict_set: set[str] | None = None,
    row_hint: str = "",
) -> str:
    exposure = as_str(value).strip().lower().replace("_", "-")
    if not exposure:
        if strict_set is not None:
            allowed = "/".join(sorted(strict_set))
            prefix = f"Services row {row_hint}: " if row_hint else ""
            raise RuntimeError(f"{prefix}exposure is required and must be one of {allowed}")
        return EXPOSURE_PUBLIC

    exposure = _EXPOSURE_ALIASES.get(exposure, exposure)

    if strict_set is not None and exposure not in strict_set:
        allowed = "/".join(sorted(strict_set))
        prefix = f"Services row {row_hint}: " if row_hint else ""
        raise RuntimeError(f"{prefix}unsupported exposure {exposure!r}; use only {allowed}")

    return exposure


def split_fqdn_list(
    value: Any,
    *,
    keep_ports: bool = False,
    debug: bool = False,
) -> list[tuple[str, int | None]]:
    raw = as_str(value)
    if not raw:
        return []

    values: list[tuple[str, int | None]] = []
    for item in raw.split(";"):
        token = item.strip()
        if not token:
            continue

        fqdn_part = token
        port_override: int | None = None

        if keep_ports:
            if ":" in token:
                fqdn_part, port_part = token.rsplit(":", 1)
                port_part = port_part.strip()
                if port_part:
                    try:
                        parsed_port = int(port_part)
                        if 1 <= parsed_port <= 65535:
                            port_override = parsed_port
                        elif debug:
                            print(
                                f"[debug] Ignoring invalid extra_cname port {port_part!r} in {token!r}",
                                file=sys.stderr,
                            )
                    except ValueError:
                        if debug:
                            print(
                                f"[debug] Ignoring non-integer extra_cname port {port_part!r} in {token!r}",
                                file=sys.stderr,
                            )
        elif ":" in token:
            fqdn_part = token.split(":", 1)[0]

        fqdn = fqdn_part.strip().lower().rstrip(".")
        if fqdn:
            values.append((fqdn, port_override))

    return values
