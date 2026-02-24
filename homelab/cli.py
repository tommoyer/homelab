from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from . import (
    caddyfile,
    mikrotik_backup,
    mikrotik_dhcp_leases,
    mikrotik_firewall,
    pihole,
)

COMMANDS: dict[str, tuple[str, object]] = {
    "run": ("Run multiple features", object()),
    "pihole": ("Generate/apply Pi-hole config", pihole),
    "mikrotik-backup": ("Back up MikroTik RouterOS /export", mikrotik_backup),
    "mikrotik-dhcp": ("Generate/apply MikroTik DHCP static leases", mikrotik_dhcp_leases),
    "mikrotik-firewall": ("Generate/apply MikroTik firewall dstnat/filter rules", mikrotik_firewall),
    "caddy": ("Generate/deploy Caddyfile from Google Sheets", caddyfile),
}


def _print_help() -> None:
    print("usage: python -m homelab [-h] <command> [args...]\n")
    print("Unified CLI for this homelab repo.\n")
    print("commands:")
    width = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name.ljust(width)}  {desc}")
    print("\nRun: python -m homelab <command> --help")


@dataclass(frozen=True)
class _RunPlan:
    apply: bool
    yes: bool
    features: list[str]


def _build_run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m homelab run",
        description=(
            "Run multiple homelab features in a single invocation. "
            "By default, runs all features unless you specify any feature flags."
        ),
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Forward --apply to apply-capable features (pihole, mikrotik-dhcp, mikrotik-firewall, caddy). "
            "mikrotik-backup always performs a backup."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Forward --yes (currently used by mikrotik-dhcp).",
    )

    # If any of these are set, we treat it as an explicit allow-list.
    parser.add_argument("--pihole", action="store_true", help="Include Pi-hole config generation/apply")
    parser.add_argument(
        "--mikrotik-dhcp",
        action="store_true",
        help="Include MikroTik DHCP leases generation/apply",
    )
    parser.add_argument(
        "--mikrotik-firewall",
        action="store_true",
        help="Include MikroTik firewall dstnat/filter generation/apply",
    )
    parser.add_argument(
        "--mikrotik-backup",
        action="store_true",
        help="Include MikroTik /export backup",
    )
    parser.add_argument("--caddy", action="store_true", help="Include Caddyfile generation/deploy")

    # Optional explicit disables.
    parser.add_argument("--no-pihole", action="store_true", help="Exclude Pi-hole")
    parser.add_argument("--no-mikrotik-dhcp", action="store_true", help="Exclude MikroTik DHCP")
    parser.add_argument("--no-mikrotik-firewall", action="store_true", help="Exclude MikroTik firewall")
    parser.add_argument("--no-mikrotik-backup", action="store_true", help="Exclude MikroTik backup")
    parser.add_argument("--no-caddy", action="store_true", help="Exclude Caddy")

    return parser


def _plan_run(argv: list[str]) -> _RunPlan:
    parser = _build_run_parser()
    args = parser.parse_args(argv)

    explicit_enables = {
        "pihole": bool(args.pihole),
        "mikrotik-dhcp": bool(args.mikrotik_dhcp),
        "mikrotik-firewall": bool(args.mikrotik_firewall),
        "mikrotik-backup": bool(args.mikrotik_backup),
        "caddy": bool(args.caddy),
    }
    explicit_disables = {
        "pihole": bool(args.no_pihole),
        "mikrotik-dhcp": bool(args.no_mikrotik_dhcp),
        "mikrotik-firewall": bool(args.no_mikrotik_firewall),
        "mikrotik-backup": bool(args.no_mikrotik_backup),
        "caddy": bool(args.no_caddy),
    }

    for feature, enabled in explicit_enables.items():
        if enabled and explicit_disables.get(feature):
            raise SystemExit(f"Error: cannot combine --{feature} and --no-{feature}")

    any_explicit = any(explicit_enables.values())
    if any_explicit:
        features = [name for name, enabled in explicit_enables.items() if enabled]
    else:
        features = list(explicit_enables.keys())

    features = [name for name in features if not explicit_disables.get(name, False)]

    # Default safety-ish ordering: backup first, then changes.
    ordered = [
        name
        for name in [
            "mikrotik-backup",
            "mikrotik-firewall",
            "mikrotik-dhcp",
            "pihole",
            "caddy",
        ]
        if name in features
    ]

    return _RunPlan(apply=bool(args.apply), yes=bool(args.yes), features=ordered)


def _run_mode(argv: list[str]) -> int:
    plan = _plan_run(argv)
    if not plan.features:
        print("Nothing to do (all features disabled)", file=sys.stderr)
        return 0

    for feature in plan.features:
        try:
            if feature == "mikrotik-backup":
                code = int(mikrotik_backup.main([]))
            elif feature == "mikrotik-dhcp":
                f_argv: list[str] = []
                if plan.apply:
                    f_argv.append("--apply")
                if plan.yes:
                    f_argv.append("--yes")
                code = int(mikrotik_dhcp_leases.main(f_argv))
            elif feature == "mikrotik-firewall":
                f_argv = []
                if plan.apply:
                    f_argv.append("--apply")
                if plan.yes:
                    f_argv.append("--yes")
                code = int(mikrotik_firewall.main(f_argv))
            elif feature == "pihole":
                f_argv = ["--apply"] if plan.apply else []
                code = int(pihole.main(f_argv))
            elif feature == "caddy":
                f_argv = ["--apply"] if plan.apply else []
                code = int(caddyfile.main(f_argv))
            else:
                print(f"Error: unknown run feature: {feature}", file=sys.stderr)
                return 2

            if code != 0:
                print(f"Error: '{feature}' failed with exit code {code}", file=sys.stderr)
                return code
        except KeyboardInterrupt:
            print("Aborted", file=sys.stderr)
            return 130

    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in {"-h", "--help"}:
        _print_help()
        return 0

    command = argv[0]
    cmd_argv = argv[1:]

    if command == "run":
        return _run_mode(cmd_argv)

    entry = COMMANDS.get(command)
    if entry is None:
        print(f"Error: unknown command: {command}", file=sys.stderr)
        _print_help()
        return 2

    _, module = entry

    try:
        return int(module.main(cmd_argv))  # type: ignore[attr-defined]
    except KeyboardInterrupt:
        print("Aborted", file=sys.stderr)
        return 130
