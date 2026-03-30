"""Shared Tailscale status helpers.

Provides a cached interface to ``tailscale status --json`` so that multiple
modules within a single CLI invocation share one subprocess call.

The functions here are public so that :mod:`homelab.resolver`,
the Ansible inventory script, and any other module can resolve hostnames
against the Tailnet peer list.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

from .sheets import as_str
from .ssh import require_command

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_cached_status: dict[str, Any] | None = None
_cached_lookup: dict[str, str] | None = None


def clear_cache() -> None:
    """Reset the module-level cache (useful for tests)."""
    global _cached_status, _cached_lookup
    _cached_status = None
    _cached_lookup = None


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def normalize_name(value: str) -> str:
    """Lower-case, strip, remove trailing dots."""
    return (value or "").strip().lower().rstrip(".")


def name_candidates(value: str) -> list[str]:
    """Return lookup candidates: the normalized name and its short-name."""
    normalized = normalize_name(value)
    if not normalized:
        return []
    out = [normalized]
    if "." in normalized:
        out.append(normalized.split(".", 1)[0])
    return list(dict.fromkeys(out))


def extract_tailscale_ip(peer: dict[str, Any]) -> str | None:
    """Return the first Tailscale IP from a peer dict, or *None*."""
    ips = peer.get("TailscaleIPs")
    if isinstance(ips, list):
        for item in ips:
            value = as_str(item)
            if value:
                return value
    return None


def build_tailscale_lookup(status: dict[str, Any]) -> dict[str, str]:
    """Build a ``{name: tailscale_ip}`` dict from ``tailscale status`` JSON.

    Keys include ``HostName``, ``DNSName``, and ``Name`` for both the local
    node (``Self``) and every peer.  Short-name variants (everything before
    the first dot) are also added.
    """
    lookup: dict[str, str] = {}

    def _index_peer(peer: dict[str, Any]) -> None:
        peer_ip = extract_tailscale_ip(peer)
        if not peer_ip:
            return
        for key_name in (
            as_str(peer.get("HostName")),
            as_str(peer.get("DNSName")),
            as_str(peer.get("Name")),
        ):
            for candidate in name_candidates(key_name):
                lookup.setdefault(candidate, peer_ip)

    self_peer = status.get("Self")
    if isinstance(self_peer, dict):
        _index_peer(self_peer)

    peers = status.get("Peer")
    if isinstance(peers, dict):
        for peer in peers.values():
            if isinstance(peer, dict):
                _index_peer(peer)

    return lookup


def read_tailscale_status(*, command: str = "tailscale") -> dict[str, Any]:
    """Run ``tailscale status --json`` and return the parsed JSON dict.

    Raises :class:`RuntimeError` if the command is missing, fails, or
    returns non-JSON output.
    """
    require_command(command)
    result = subprocess.run(
        [command, "status", "--json"],
        check=True,
        text=True,
        capture_output=True,
    )
    try:
        payload = json.loads(result.stdout)
    except Exception as exc:
        raise RuntimeError(f"failed to parse tailscale status JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("tailscale status JSON response is not an object")
    return payload


# ---------------------------------------------------------------------------
# High-level cached interface
# ---------------------------------------------------------------------------


def get_tailscale_status(*, command: str = "tailscale") -> dict[str, Any]:
    """Return *cached* Tailscale status (calls the CLI at most once per process)."""
    global _cached_status
    if _cached_status is None:
        _cached_status = read_tailscale_status(command=command)
    return _cached_status


def get_tailscale_lookup(*, command: str = "tailscale") -> dict[str, str]:
    """Return *cached* ``{name: tailscale_ip}`` lookup dict."""
    global _cached_lookup
    if _cached_lookup is None:
        status = get_tailscale_status(command=command)
        _cached_lookup = build_tailscale_lookup(status)
    return _cached_lookup


def get_tailscale_lookup_safe(*, command: str = "tailscale") -> dict[str, str]:
    """Like :func:`get_tailscale_lookup` but returns ``{}`` on any error.

    This is the preferred entry-point for modules that want Tailscale
    resolution but should degrade gracefully when the CLI is unavailable or
    the daemon is not running.
    """
    try:
        return get_tailscale_lookup(command=command)
    except Exception as exc:
        logger.debug("tailscale lookup unavailable (falling back): %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def resolve_tailscale_ip(*, node_name: str, lookup: dict[str, str]) -> str | None:
    """Resolve *node_name* to its Tailscale IP using *lookup*, or *None*."""
    for candidate in name_candidates(node_name):
        ip = lookup.get(candidate)
        if ip:
            return ip
    return None


def resolve_tailscale_fqdn(
    *,
    node_name: str,
    tailnet_domain: str,
    lookup: dict[str, str],
) -> str | None:
    """Return ``<short_hostname>.<tailnet_domain>`` if *node_name* is on the Tailnet.

    Returns *None* when the node is not found in *lookup* or when
    *tailnet_domain* is empty.
    """
    if not tailnet_domain:
        return None
    ip = resolve_tailscale_ip(node_name=node_name, lookup=lookup)
    if ip is None:
        return None
    # Use the short hostname (first candidate) for the FQDN.
    candidates = name_candidates(node_name)
    short = candidates[-1] if candidates else normalize_name(node_name)
    return f"{short}.{tailnet_domain.strip().rstrip('.')}"


def is_on_tailnet(*, node_name: str, lookup: dict[str, str]) -> bool:
    """Return *True* if *node_name* appears in the Tailscale peer list."""
    return resolve_tailscale_ip(node_name=node_name, lookup=lookup) is not None
