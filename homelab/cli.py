from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

from .commands import COMMANDS
from .logging_utils import configure_logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _RunPlan:
    apply: bool
    tailnet: str | None
    features: list[str]


def _print_help() -> None:
    print("usage: python -m homelab [-h] [--debug] [--apply] <command> [args...]\n")
    print("Unified CLI for this homelab repo.\n")
    print("global options:")
    print("  --debug           Enable verbose debug logging to stderr")
    print("  --apply           Apply changes (deploy, dns, caddy)")
    print("")
    print("commands:")
    width = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name.ljust(width)}  {desc}")
    print("\nRun: python -m homelab <command> --help")


def _parse_global_options(argv: list[str]) -> tuple[bool, bool, list[str]]:
    """Parse global options that appear before the <command>.

    We intentionally only consume options *before* the command name so that
    --debug/--apply are global-only flags.
    
    Returns:
        (debug, apply, remaining_argv)
    """

    debug = False
    apply = False
    rest = list(argv)

    while rest and rest[0].startswith("-"):
        flag = rest.pop(0)

        if flag in {"-h", "--help"}:
            _print_help()
            raise SystemExit(0)

        if flag == "--debug":
            debug = True
            continue
        
        if flag == "--apply":
            apply = True
            continue

        print(f"Error: unknown global option: {flag}", file=sys.stderr)
        _print_help()
        raise SystemExit(2)

    return debug, apply, rest


def _build_run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m homelab run",
        description=(
            "Run multiple homelab features in a single invocation. "
            "By default, runs all features unless you specify any feature flags."
        ),
    )

    # If any of these are set, we treat it as an explicit allow-list.
    parser.add_argument("--dns", action="store_true", help="Include DNS generation/apply")
    parser.add_argument(
        "--mikrotik",
        action="store_true",
        help="Include prompt-driven MikroTik command generation (single or batch)",
    )
    parser.add_argument(
        "--caddy",
        action="store_true",
        help="Include Caddyfile generation/deploy",
    )
    parser.add_argument(
        "--tailnet",
        default=None,
        help=(
            "Override Tailscale tailnet domain for private DNS targets "
            "(forwarded to dns --tailnet)"
        ),
    )
    parser.add_argument(
        "--tailscale-install",
        action="store_true",
        help="Include Tailscale installation based on Nodes tailscale_install_method",
    )

    # Optional explicit disables.
    parser.add_argument("--no-dns", action="store_true", help="Exclude DNS")
    parser.add_argument("--no-mikrotik", action="store_true", help="Exclude MikroTik prompt generator")
    parser.add_argument("--no-caddy", action="store_true", help="Exclude Caddy")
    parser.add_argument("--no-tailscale-install", action="store_true", help="Exclude tailscale_install")

    return parser


def _plan_run(argv: list[str]) -> _RunPlan:
    parser = _build_run_parser()
    args = parser.parse_args(argv)

    explicit_enables = {
        "dns": bool(args.dns),
        "mikrotik": bool(args.mikrotik),
        "caddy": bool(args.caddy),
        "tailscale_install": bool(getattr(args, "tailscale_install", False)),
    }
    explicit_disables = {
        "dns": bool(args.no_dns),
        "mikrotik": bool(args.no_mikrotik),
        "caddy": bool(args.no_caddy),
        "tailscale_install": bool(getattr(args, "no_tailscale_install", False)),
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
            "dns",
            "caddy",
            "tailscale_install",
        ]
        if name in features
    ]

    return _RunPlan(apply=False, tailnet=getattr(args, "tailnet", None), features=ordered)


def _run_mode(argv: list[str], *, debug: bool, apply: bool) -> int:
    logger.debug("run: argv=%r debug=%s apply=%s", argv, debug, apply)

    plan = _plan_run(argv)
    plan = _RunPlan(apply=apply, tailnet=plan.tailnet, features=plan.features)
    logger.debug("run: plan=%r", plan)
    if not plan.features:
        print("Nothing to do (all features disabled)", file=sys.stderr)
        return 0

    for feature in plan.features:
        try:
            module = COMMANDS.get(feature, ("", None))[1]
            if module is None or not hasattr(module, "main"):
                print(f"Error: unknown run feature: {feature}", file=sys.stderr)
                return 2

            if feature == "mikrotik":
                f_argv: list[str] = []
                if debug:
                    f_argv.append("--_debug")
                code = int(module.main(f_argv))  # type: ignore[attr-defined]
            elif feature == "dns":
                f_argv = []
                if debug:
                    f_argv.append("--_debug")
                if plan.apply:
                    f_argv.append("--_apply")
                if plan.tailnet:
                    f_argv.extend(["--tailnet", plan.tailnet])
                code = int(module.main(f_argv))  # type: ignore[attr-defined]
            elif feature == "caddy":
                f_argv = []
                if debug:
                    f_argv.append("--_debug")
                if plan.apply:
                    f_argv.append("--_apply")
                code = int(module.main(f_argv))  # type: ignore[attr-defined]
            elif feature == "tailscale_install":
                f_argv = []
                if debug:
                    f_argv.append("--_debug")
                if plan.apply:
                    f_argv.append("--_apply")
                code = int(module.main(f_argv))  # type: ignore[attr-defined]
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

    debug, apply, argv = _parse_global_options(argv)
    configure_logging(debug=debug)
    if debug:
        logger.debug("global debug enabled")
    if apply:
        logger.debug("global apply enabled")

    if not argv or argv[0] in {"-h", "--help"}:
        _print_help()
        return 0

    command = argv[0]
    cmd_argv = argv[1:]

    if (
        "--debug" in cmd_argv
        or "--apply" in cmd_argv
        or "--_debug" in cmd_argv
        or "--_apply" in cmd_argv
    ):
        print(
            "Error: --debug and --apply are global-only flags. Place them before the command, "
            "e.g. 'python -m homelab --debug --apply <command> ...'",
            file=sys.stderr,
        )
        return 2

    # Forward global flags to subcommands that support them
    forwarded_flags = []

    # Commands that support --debug
    if debug:
        if command in {"caddy", "mikrotik", "deploy", "dns", "tailscale_install"}:
            forwarded_flags.append("--_debug")

    # Commands that support --apply
    if apply:
        if command in {"deploy", "dns", "caddy", "tailscale_install"}:
            forwarded_flags.append("--_apply")
    
    if forwarded_flags:
        cmd_argv = forwarded_flags + cmd_argv

    if command == "run":
        # For run-mode, forward global flags to sub-tools
        if debug:
            logger.debug("forwarding global --debug to run-mode subcommands")
        if apply:
            logger.debug("forwarding global --apply to run-mode subcommands")
        return _run_mode(cmd_argv, debug=debug, apply=apply)

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
