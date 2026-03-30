"""Unified host resolver: Tailscale-first with Google Sheet fallback.

The :class:`HostResolver` tries, in order:

1. If the value is already a valid IP address → return unchanged.
2. If Tailscale is enabled and the hostname is on the Tailnet → return the
   Tailscale FQDN (``<short>.<tailnet_domain>``) or IP, depending on which
   method is called.
3. Fall back to the Google Sheet ``nodes_lookup`` dict (hostname → LAN IP).
4. Return the original value unchanged (it may already be a usable FQDN).

Usage::

    resolver = build_resolver(config)          # or build_resolver(config, nodes_df)
    target   = resolver.resolve("caddy")       # → "caddy.tail12345.ts.net" or "192.168.20.2"
    ip       = resolver.resolve_ip("caddy")    # → "100.117.137.2" or "192.168.20.2"
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

import pandas as pd

from .config import get_table
from .sheets import load_nodes_lookup
from .tailscale import (
    get_tailscale_lookup_safe,
    resolve_tailscale_fqdn,
    resolve_tailscale_ip,
)

logger = logging.getLogger(__name__)


class HostResolver:
    """Resolve a hostname to a Tailscale FQDN/IP with a Sheets fallback.

    Parameters
    ----------
    tailscale_lookup:
        ``{name: tailscale_ip}`` mapping produced by
        :func:`~homelab.tailscale.build_tailscale_lookup`.
    tailnet_domain:
        The Tailnet domain suffix (e.g. ``tail12345.ts.net``).
    nodes_lookup:
        ``{hostname|dns_name: lan_ip}`` mapping from the Google Sheet.
    use_tailscale:
        Master toggle.  When *False*, Tailscale resolution is skipped
        entirely and the resolver falls straight through to the Sheets
        lookup.
    """

    def __init__(
        self,
        *,
        tailscale_lookup: dict[str, str],
        tailnet_domain: str,
        nodes_lookup: dict[str, str],
        use_tailscale: bool = True,
    ) -> None:
        self.tailscale_lookup = tailscale_lookup
        self.tailnet_domain = tailnet_domain.strip().rstrip(".") if tailnet_domain else ""
        self.nodes_lookup = nodes_lookup
        self.use_tailscale = use_tailscale

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, hostname: str) -> str:
        """Return the best reachable address for *hostname*.

        Resolution order:
        1. Already an IP → return as-is.
        2. Tailscale FQDN (``short.tailnet_domain``) if on the Tailnet.
        3. LAN IP from the Google Sheet.
        4. Original value unchanged.
        """
        raw = (hostname or "").strip()
        if not raw:
            return raw

        if self._is_ip(raw):
            return raw

        if self.use_tailscale and self.tailnet_domain:
            fqdn = resolve_tailscale_fqdn(
                node_name=raw,
                tailnet_domain=self.tailnet_domain,
                lookup=self.tailscale_lookup,
            )
            if fqdn:
                logger.debug("resolve(%s) -> tailscale fqdn %s", raw, fqdn)
                return fqdn

        lan_ip = self.nodes_lookup.get(raw.lower())
        if lan_ip:
            logger.debug("resolve(%s) -> sheet ip %s", raw, lan_ip)
            return lan_ip

        logger.debug("resolve(%s) -> passthrough", raw)
        return raw

    def resolve_ip(self, hostname: str) -> str:
        """Like :meth:`resolve` but returns the Tailscale *IP* (100.x.x.x)
        instead of the FQDN when the host is on the Tailnet.

        This is useful for config files that require an actual IP address
        rather than a DNS name.
        """
        raw = (hostname or "").strip()
        if not raw:
            return raw

        if self._is_ip(raw):
            return raw

        if self.use_tailscale:
            ts_ip = resolve_tailscale_ip(
                node_name=raw,
                lookup=self.tailscale_lookup,
            )
            if ts_ip:
                logger.debug("resolve_ip(%s) -> tailscale ip %s", raw, ts_ip)
                return ts_ip

        lan_ip = self.nodes_lookup.get(raw.lower())
        if lan_ip:
            logger.debug("resolve_ip(%s) -> sheet ip %s", raw, lan_ip)
            return lan_ip

        logger.debug("resolve_ip(%s) -> passthrough", raw)
        return raw

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _is_ip(value: str) -> bool:
        try:
            ipaddress.ip_address(value.split("/", 1)[0])
            return True
        except ValueError:
            return False


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------


def build_resolver(
    config: dict[str, Any],
    nodes_df: pd.DataFrame | None = None,
    *,
    use_tailscale: bool | None = None,
) -> HostResolver:
    """Convenience factory that wires everything together from config.

    Parameters
    ----------
    config:
        Parsed TOML config (the full dict, not a single section).
    nodes_df:
        Optional Nodes :class:`~pandas.DataFrame`.  When supplied the
        resolver will include the Sheets-based hostname→IP fallback.
    use_tailscale:
        Explicit override.  ``None`` means read ``[tailscale].enabled``
        from *config* (default ``True``).
    """
    ts_cfg = get_table(config, "tailscale")
    tailnet_domain: str = str(ts_cfg.get("tailnet_domain", "") or "")
    ts_command: str = str(ts_cfg.get("command", "tailscale") or "tailscale")

    if use_tailscale is None:
        use_tailscale = bool(ts_cfg.get("enabled", True))

    tailscale_lookup: dict[str, str] = {}
    if use_tailscale:
        tailscale_lookup = get_tailscale_lookup_safe(command=ts_command)
        if not tailscale_lookup:
            logger.info(
                "Tailscale peer list is empty or unavailable; "
                "falling back to Sheet IPs for all hosts"
            )

    nodes_lookup: dict[str, str] = {}
    if nodes_df is not None:
        nodes_lookup = load_nodes_lookup(nodes_df)

    return HostResolver(
        tailscale_lookup=tailscale_lookup,
        tailnet_domain=tailnet_domain,
        nodes_lookup=nodes_lookup,
        use_tailscale=use_tailscale,
    )
