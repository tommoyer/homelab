from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

from . import caddyfile, deploy, dnscontrol, dnsmasq, mikrotik_prompt, pihole
from .logging_utils import configure_logging

logger = logging.getLogger(__name__)

COMMANDS: dict[str, tuple[str, object]] = {
    "run": ("Run multiple features", object()),
    "pihole": ("Generate/apply Pi-hole config", pihole),
    "dnsmasq": ("Generate dnsmasq config from Services + Tailscale status", dnsmasq),
    "dnscontrol": ("Generate dnscontrol files for Cloudflare public DNS", dnscontrol),
    "mikrotik": ("Prompt-driven single-service MikroTik command generator", mikrotik_prompt),
    "caddy": ("Generate/deploy Caddyfile from Google Sheets", caddyfile),
    "deploy": ("Deploy a complete node/service", deploy),
}


def _print_help() -> None:
    print("usage: python -m homelab [-h] [--debug] <command> [args...]\n")
    print("Unified CLI for this homelab repo.\n")
    print("global options:")
    print("  --debug           Enable verbose debug logging to stderr")
    print("")
    print("commands:")
    width = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name.ljust(width)}  {desc}")
    print("\nRun: python -m homelab <command> --help")


def _parse_global_options(argv: list[str]) -> tuple[bool, list[str]]:
    """Parse global options that appear before the <command>.

    We intentionally only consume options *before* the command name so that
    subcommands can continue to support their own flags (including --debug).
    """

    debug = False
    rest = list(argv)

    while rest and rest[0].startswith("-"):
        flag = rest.pop(0)

        if flag in {"-h", "--help"}:
            _print_help()
            raise SystemExit(0)

        if flag == "--debug":
            debug = True
            continue

        print(f"Error: unknown global option: {flag}", file=sys.stderr)
        _print_help()
        raise SystemExit(2)

    return debug, rest


@dataclass(frozen=True)
class _RunPlan:
    apply: bool
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
            "Forward --apply to apply-capable features (pihole, dnsmasq, caddy, dnscontrol). Without "
            "--apply, tools run in dry-run mode and print what "
            "would be done."
        ),
    )
    # If any of these are set, we treat it as an explicit allow-list.
    parser.add_argument("--pihole", action="store_true", help="Include Pi-hole config generation/apply")
    parser.add_argument(
        "--mikrotik",
        action="store_true",
        help="Include prompt-driven MikroTik single-service command generation",
    )
    parser.add_argument(
        "--caddy",
        action="store_true",
        help="Include Caddyfile generation/deploy",
    )
    parser.add_argument(
        "--dnsmasq",
        action="store_true",
        help="Include dnsmasq address generation/deploy",
    )
    parser.add_argument(
        "--dnscontrol",
        action="store_true",
        help="Include dnscontrol public DNS generation/apply",
    )

    # Optional explicit disables.
    parser.add_argument("--no-pihole", action="store_true", help="Exclude Pi-hole")
    parser.add_argument("--no-mikrotik", action="store_true", help="Exclude MikroTik prompt generator")
    parser.add_argument("--no-caddy", action="store_true", help="Exclude Caddy")
    parser.add_argument("--no-dnsmasq", action="store_true", help="Exclude dnsmasq")
    parser.add_argument("--no-dnscontrol", action="store_true", help="Exclude dnscontrol")

    return parser


def _plan_run(argv: list[str]) -> _RunPlan:
    parser = _build_run_parser()
    args = parser.parse_args(argv)

    explicit_enables = {
        "pihole": bool(args.pihole),
        "mikrotik": bool(args.mikrotik),
        "caddy": bool(args.caddy),
        "dnsmasq": bool(args.dnsmasq),
        "dnscontrol": bool(args.dnscontrol),
    }
    explicit_disables = {
        "pihole": bool(args.no_pihole),
        "mikrotik": bool(args.no_mikrotik),
        "caddy": bool(args.no_caddy),
        "dnsmasq": bool(args.no_dnsmasq),
        "dnscontrol": bool(args.no_dnscontrol),
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

    # Default ordering.
    ordered = [
        name
        for name in [
            "mikrotik",
            "pihole",
            "dnsmasq",
            "caddy",
            "dnscontrol",
        ]
        if name in features
    ]

    return _RunPlan(apply=bool(args.apply), features=ordered)


def _run_mode(argv: list[str], *, debug: bool) -> int:
    logger.debug("run: argv=%r debug=%s", argv, debug)
    plan = _plan_run(argv)
    logger.debug("run: plan=%r", plan)
    if not plan.features:
        print("Nothing to do (all features disabled)", file=sys.stderr)
        return 0

    for feature in plan.features:
        try:
            if feature == "mikrotik":
                f_argv: list[str] = []
                if debug:
                    f_argv.append("--debug")
                code = int(mikrotik_prompt.main(f_argv))
            elif feature == "pihole":
                f_argv = ["--apply"] if plan.apply else []
                code = int(pihole.main(f_argv))
            elif feature == "caddy":
                f_argv = []
                if debug:
                    f_argv.append("--debug")
                if plan.apply:
                    f_argv.append("--apply")
                code = int(caddyfile.main(f_argv))
            elif feature == "dnsmasq":
                f_argv = []
                if debug:
                    f_argv.append("--debug")
                if plan.apply:
                    f_argv.append("--apply")
                code = int(dnsmasq.main(f_argv))
            elif feature == "dnscontrol":
                f_argv = []
                if debug:
                    f_argv.append("--debug")
                if plan.apply:
                    f_argv.append("--apply")
                code = int(dnscontrol.main(f_argv))
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

    debug, argv = _parse_global_options(argv)
    configure_logging(debug=debug)
    logger.debug("global debug enabled")

    if not argv or argv[0] in {"-h", "--help"}:
        _print_help()
        return 0

    command = argv[0]
    cmd_argv = argv[1:]

    # If global --debug was enabled, try to forward it to subcommands that
    # already support their own --debug flag (preserves existing UX).
    if debug and "--debug" not in cmd_argv and command in {"caddy", "mikrotik"}:
        cmd_argv = ["--debug", *cmd_argv]

    if command == "run":
        # For run-mode we don't have a dedicated flag, but forwarding --debug to
        # sub-tools makes their existing debug output visible.
        if debug:
            logger.debug("forwarding global --debug to run-mode subcommands")
        return _run_mode(cmd_argv, debug=debug)

    entry = COMMANDS.get(command)
    if entry is None:
        print(f"Error: unknown command: {command}", file=sys.stderr)
        _print_help()
        return 2

    _, module = entry

    try:
        logger.debug("dispatch: command=%s argv=%r", command, cmd_argv)
        return int(module.main(cmd_argv))  # type: ignore[attr-defined]
    except KeyboardInterrupt:
        print("Aborted", file=sys.stderr)
        return 130
