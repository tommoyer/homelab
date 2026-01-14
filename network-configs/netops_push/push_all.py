from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .update_pihole import main as pihole_main
from .update_mikrotik import main as mikrotik_main
from .update_caddy import main as caddy_main
from .update_cloudflare_dnscontrol import main as cloudflare_main


def main() -> int:
    ap = argparse.ArgumentParser(description="Push all updates (Pi-hole -> Mikrotik -> Cloudflare). Fail fast.")
    ap.add_argument("--assets", required=True, type=Path)
    ap.add_argument("--dns-names", required=True, type=Path)
    ap.add_argument("--services", required=True, type=Path)
    ap.add_argument("--vlans", required=True, type=Path)

    ap.add_argument("--cache-dir", default=Path("cache"), type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--identity-file", default=None)

    # Mikrotik overrides (optional)
    ap.add_argument("--mikrotik-host", default=None)
    ap.add_argument("--mikrotik-user", default=None)
    ap.add_argument("--mikrotik-port", type=int, default=22)
    ap.add_argument("--wan-list-name", default="WAN")
    ap.add_argument("--vlan-ifname-template", default="vlan{vlan_tag}")

    # dnscontrol
    ap.add_argument("--dnscontrol-dir", required=True, type=Path)
    ap.add_argument("--dnscontrol-bin", default="dnscontrol")
    ap.add_argument("--zones", nargs="*", default=None)
    ap.add_argument("--include-path", default=None)
    ap.add_argument("--no-check", action="store_true")

    args = ap.parse_args()

    # Pi-hole
    sys.argv = [
        "update_pihole",
        "--assets", str(args.assets),
        "--dns-names", str(args.dns_names),
        "--services", str(args.services),
        "--vlans", str(args.vlans),
        "--cache-dir", str(args.cache_dir),
    ] + (["--dry-run"] if args.dry_run else []) + (["--keep"] if args.keep else []) + (
        ["--identity-file", args.identity_file] if args.identity_file else []
    )
    rc = pihole_main()
    if rc != 0:
        return rc

    # Mikrotik
    sys.argv = [
        "update_mikrotik",
        "--assets", str(args.assets),
        "--dns-names", str(args.dns_names),
        "--services", str(args.services),
        "--vlans", str(args.vlans),
        "--wan-list-name", args.wan_list_name,
        "--vlan-ifname-template", args.vlan_ifname_template,
    ] + (["--dry-run"] if args.dry_run else []) + (
        ["--identity-file", args.identity_file] if args.identity_file else []
    )
    if args.mikrotik_host and args.mikrotik_user:
        sys.argv += ["--mikrotik-host", args.mikrotik_host, "--mikrotik-user", args.mikrotik_user, "--mikrotik-port", str(args.mikrotik_port)]
    rc = mikrotik_main()
    if rc != 0:
        return rc

    # Caddy
    sys.argv = [
        "update_caddy",
        "--assets", str(args.assets),
        "--dns-names", str(args.dns_names),
        "--services", str(args.services),
        "--vlans", str(args.vlans),
        "--cache-dir", str(args.cache_dir),
    ] + (["--dry-run"] if args.dry_run else []) + (["--keep"] if args.keep else []) + (
        ["--identity-file", args.identity_file] if args.identity_file else []
    )
    rc = caddy_main()
    if rc != 0:
        return rc

    # Cloudflare
    sys.argv = [
        "update_cloudflare",
        "--assets", str(args.assets),
        "--dns-names", str(args.dns_names),
        "--services", str(args.services),
        "--vlans", str(args.vlans),
        "--cache-dir", str(args.cache_dir),
        "--dnscontrol-dir", str(args.dnscontrol_dir),
        "--dnscontrol-bin", args.dnscontrol_bin,
    ] + (["--dry-run"] if args.dry_run else []) + (["--no-check"] if args.no_check else [])

    if args.zones:
        sys.argv += ["--zones"] + args.zones
    if args.include_path:
        sys.argv += ["--include-path", args.include_path

        ]
    rc = cloudflare_main()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

