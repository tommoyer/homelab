from __future__ import annotations

import argparse
import curses
import ipaddress
import logging
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .cli_common import (
    add_apply_argument,
    add_sheet_arguments,
    bootstrap_config_and_logging,
    build_base_parser,
)
from .config import (
    get_config_value,
    get_effective_table,
    load_toml_or_exit,
    resolve_path_relative_to_config,
)
from .resolver import build_resolver
from .sheets import as_str, df_with_normalized_columns, get_sheet_df, parse_bool
from .ssh import prefix_sshpass, require_command, sshpass_env_from_password_env
from .tailscale import get_tailscale_lookup_safe, is_on_tailnet

logger = logging.getLogger(__name__)

TAILSCALE_INSTALL_SCRIPT_METHOD = "tailscale install script"
PROXMOX_HELPER_SCRIPT_METHOD = "proxmox helper script"
DEFAULT_PROXMOX_TAILSCALE_HELPER_URL = (
    "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/addon/add-tailscale-lxc.sh"
)


def _normalize_method(value: object) -> str:
    return as_str(value).strip().lower()


def _select_disconnected_node(nodes: list[tuple[str, Any]]) -> str | None:
    if not nodes:
        return None

    if not sys.stdin.isatty():
        return None

    items = []
    for hostname, row in nodes:
        method = as_str(row.get("tailscale_install_method"))
        items.append({"hostname": hostname, "method": method})

    def _curses_menu(stdscr: "curses._CursesWindow") -> str | None:  # type: ignore[name-defined]
        curses.curs_set(0)
        selected = 0

        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()

            stdscr.addstr(0, 0, "=" * min(width - 1, 80))
            stdscr.addstr(1, 0, "  SELECT NODE FOR TAILSCALE INSTALL")
            stdscr.addstr(2, 0, "=" * min(width - 1, 80))
            stdscr.addstr(3, 0, "Only disconnected nodes are shown")
            stdscr.addstr(4, 0, "Use ↑/↓ to select, Enter to continue, q to quit")
            stdscr.addstr(5, 0, "-" * min(width - 1, 80))

            for idx, item in enumerate(items):
                prefix = "▶" if idx == selected else " "
                label = f"{prefix} {item['hostname'].ljust(24)} [{item['method']}]"
                y_pos = 7 + idx
                if y_pos < height - 1:
                    try:
                        stdscr.addstr(y_pos, 0, label[: width - 1])
                    except curses.error:
                        pass

            try:
                ch = stdscr.getch()
            except KeyboardInterrupt:
                return None

            if ch in (ord("q"), ord("Q"), 27):
                return None
            if ch == curses.KEY_UP:
                selected = (selected - 1) % len(items)
            elif ch == curses.KEY_DOWN:
                selected = (selected + 1) % len(items)
            elif ch in (10, 13, curses.KEY_ENTER):
                return items[selected]["hostname"]

        return None

    try:
        return curses.wrapper(_curses_menu)
    except KeyboardInterrupt:
        return None


def _as_int(value: Any, default: int) -> int:
    raw = as_str(value)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _extract_ip(value: str) -> str | None:
    raw = as_str(value)
    if not raw:
        return None
    first = raw.split()[0].strip()
    if "/" in first:
        first = first.split("/", 1)[0].strip()
    try:
        ipaddress.ip_address(first)
    except ValueError:
        return None
    return first


def build_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    config_path, config, globals_cfg, tool_cfg = bootstrap_config_and_logging(argv, "tailscale_install")
    deploy_cfg = get_effective_table(config, "deploy", inherit=("globals",), legacy_root_fallback=False)

    parser = build_base_parser(
        description=(
            "Install Tailscale based on Nodes sheet column 'tailscale_install_method'. "
            "Supported methods: 'Tailscale Install Script' and 'Proxmox Helper Script'."
        ),
        config_path=config_path,
        globals_cfg=globals_cfg,
        tool_cfg=tool_cfg,
    )

    add_sheet_arguments(parser, globals_cfg, nodes_gid=344016240)

    parser.add_argument(
        "hostname",
        nargs="?",
        default=None,
        help="Optional hostname filter; when omitted, processes all nodes with tailscale_install_method set",
    )

    parser.add_argument(
        "--node-user",
        default=get_config_value(tool_cfg, "node_user", get_config_value(globals_cfg, "ssh_user", "root")),
        help="SSH username used for direct node installs (Tailscale Install Script method)",
    )
    parser.add_argument(
        "--node-port",
        type=int,
        default=_as_int(get_config_value(tool_cfg, "node_port", get_config_value(globals_cfg, "ssh_port", 22)), 22),
        help="SSH port used for direct node installs",
    )
    parser.add_argument(
        "--node-identity-file",
        default=get_config_value(
            tool_cfg,
            "node_identity_file",
            get_config_value(globals_cfg, "ssh_identity_file", ""),
        ),
        help="Optional SSH identity file for direct node installs",
    )
    parser.add_argument(
        "--node-password-env",
        default=get_config_value(tool_cfg, "node_password_env", get_config_value(globals_cfg, "password_env", "")),
        help="Optional env var name containing SSH password for direct node installs",
    )

    parser.add_argument(
        "--proxmox-user",
        default=get_config_value(tool_cfg, "proxmox_user", get_config_value(deploy_cfg, "proxmox_user", "root@pam")),
        help="SSH username for Proxmox host when running Proxmox helper script",
    )
    parser.add_argument(
        "--proxmox-port",
        type=int,
        default=_as_int(
            get_config_value(
                tool_cfg,
                "proxmox_port",
                get_config_value(deploy_cfg, "proxmox_ssh_port", get_config_value(globals_cfg, "ssh_port", 22)),
            ),
            22,
        ),
        help="SSH port for Proxmox host",
    )
    parser.add_argument(
        "--proxmox-identity-file",
        default=get_config_value(
            tool_cfg,
            "proxmox_identity_file",
            get_config_value(
                deploy_cfg,
                "proxmox_ssh_identity_file",
                get_config_value(globals_cfg, "ssh_identity_file", ""),
            ),
        ),
        help="Optional SSH identity file for Proxmox host",
    )
    parser.add_argument(
        "--proxmox-password-env",
        default=get_config_value(
            tool_cfg,
            "proxmox_password_env",
            get_config_value(
                deploy_cfg,
                "proxmox_password_env",
                get_config_value(globals_cfg, "password_env", ""),
            ),
        ),
        help="Optional env var name containing SSH password for Proxmox host",
    )
    parser.add_argument(
        "--proxmox-helper-script-url",
        default=get_config_value(tool_cfg, "proxmox_helper_script_url", DEFAULT_PROXMOX_TAILSCALE_HELPER_URL),
        help="Helper script URL executed on Proxmox host for 'Proxmox Helper Script' method",
    )

    add_apply_argument(
        parser,
        help_text=(
            "If set, run remote SSH commands. Without --apply, prints the commands that would run."
        ),
    )
    return parser


def _resolve_identity_path(config_path: Path, raw_value: str) -> Path | None:
    cleaned = as_str(raw_value)
    if not cleaned:
        return None
    path = resolve_path_relative_to_config(config_path, cleaned)
    if not path.exists():
        raise FileNotFoundError(f"SSH identity file not found: {path}")
    return path


def _build_ssh_base_args(*, port: int, identity_file: Path | None) -> list[str]:
    args = [
        "ssh",
        "-t",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-p",
        str(port),
    ]
    if identity_file is not None:
        args.extend(["-i", str(identity_file)])
    return args


def _build_ssh_env_and_auth(*, apply: bool, password_env: str) -> tuple[dict[str, str] | None, bool]:
    use_sshpass = bool(as_str(password_env))
    env: dict[str, str] | None = None
    if apply:
        require_command("ssh")
        if use_sshpass:
            require_command("sshpass")
            env = sshpass_env_from_password_env(password_env=as_str(password_env))
    return env, use_sshpass


def _node_ssh_host(row: Any, *, resolver: Any) -> str:
    ip_value = _extract_ip(as_str(row.get("ip_address")))
    if ip_value:
        return ip_value

    dns_name = as_str(row.get("dns_name"))
    if dns_name:
        return resolver.resolve(dns_name)

    hostname = as_str(row.get("hostname"))
    if hostname:
        return resolver.resolve(hostname)

    return ""


def _run_direct_tailscale_install(
    *,
    hostname: str,
    row: Any,
    resolver: Any,
    config_path: Path,
    args: argparse.Namespace,
) -> bool:
    ssh_host = _node_ssh_host(row, resolver=resolver)
    if not ssh_host:
        logger.error("%s: unable to determine SSH host (need IP Address, DNS Name, or Hostname)", hostname)
        return False

    try:
        identity_file = _resolve_identity_path(config_path, as_str(args.node_identity_file))
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return False

    apply = bool(args.apply)
    env, use_sshpass = _build_ssh_env_and_auth(apply=apply, password_env=as_str(args.node_password_env))

    target = f"{as_str(args.node_user)}@{ssh_host}"
    install_cmd = "curl -fsSL https://tailscale.com/install.sh | sh"

    if not apply:
        print("Dry run (apply mode disabled): no remote changes made")
        print(f"- node: {hostname}")
        print("- method: Tailscale Install Script")
        print(f"- would ssh: {target} (port {args.node_port})")
        print(f"  {install_cmd}")
        return True

    ssh_cmd = _build_ssh_base_args(port=int(args.node_port), identity_file=identity_file)
    ssh_cmd.extend([target, install_cmd])
    ssh_cmd = prefix_sshpass(ssh_cmd, enabled=use_sshpass)

    try:
        subprocess.run(ssh_cmd, check=True, env=env)
        logger.info("%s: completed Tailscale Install Script", hostname)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("%s: Tailscale Install Script failed: %s", hostname, exc)
        return False


def _run_proxmox_helper_install(
    *,
    hostname: str,
    row: Any,
    resolver: Any,
    config_path: Path,
    args: argparse.Namespace,
) -> bool:
    proxmox_node = as_str(row.get("proxmox_node"))
    if not proxmox_node:
        logger.error("%s: tailscale_install_method is 'Proxmox Helper Script' but proxmox_node is blank", hostname)
        return False

    resolved_pve_host = resolver.resolve(proxmox_node)
    if not resolved_pve_host:
        logger.error("%s: unable to resolve proxmox_node '%s'", hostname, proxmox_node)
        return False

    try:
        identity_file = _resolve_identity_path(config_path, as_str(args.proxmox_identity_file))
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return False

    apply = bool(args.apply)
    env, use_sshpass = _build_ssh_env_and_auth(apply=apply, password_env=as_str(args.proxmox_password_env))

    target = f"{as_str(args.proxmox_user).split('@')[0]}@{resolved_pve_host}"
    script_url = as_str(args.proxmox_helper_script_url)
    helper_cmd = f"bash -c \"$(wget -qLO - {shlex.quote(script_url)})\""

    if not apply:
        print("Dry run (apply mode disabled): no remote changes made")
        print(f"- node: {hostname}")
        print("- method: Proxmox Helper Script")
        print(f"- proxmox_node: {proxmox_node} -> {resolved_pve_host}")
        print(f"- would ssh: {target} (port {args.proxmox_port})")
        print(f"  {helper_cmd}")
        return True

    ssh_cmd = _build_ssh_base_args(port=int(args.proxmox_port), identity_file=identity_file)
    ssh_cmd.extend([target, helper_cmd])
    ssh_cmd = prefix_sshpass(ssh_cmd, enabled=use_sshpass)

    try:
        subprocess.run(ssh_cmd, check=True, env=env)
        logger.info("%s: completed Proxmox Helper Script on %s", hostname, proxmox_node)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("%s: Proxmox Helper Script failed: %s", hostname, exc)
        return False


def main(argv: list[str] | argparse.Namespace | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if isinstance(argv, argparse.Namespace):
        args = argv
    else:
        parser = build_parser(argv)
        args = parser.parse_args(argv)

    config_path = args.config.expanduser().resolve()
    config = load_toml_or_exit(config_path)
    settings = get_effective_table(config, "tailscale_install", inherit=("globals",), legacy_root_fallback=False)

    sheet_url = as_str(args.sheet_url or settings.get("sheet_url"))
    nodes_gid = int(args.nodes_gid if args.nodes_gid is not None else settings.get("nodes_gid", 344016240))

    if not sheet_url:
        logger.error("Missing sheet_url")
        return 1

    try:
        nodes_df = get_sheet_df(sheet_url, nodes_gid, 30.0, "Nodes")
    except Exception as exc:
        logger.error("Error loading Nodes sheet CSV: %s", exc)
        return 1

    nodes_df = df_with_normalized_columns(nodes_df)
    if "tailscale_install_method" not in nodes_df.columns:
        logger.error("Nodes sheet is missing required column: tailscale_install_method")
        return 1

    if "hostname" not in nodes_df.columns:
        logger.error("Nodes sheet is missing required column: hostname")
        return 1

    resolver = build_resolver(config, nodes_df)
    tailscale_cfg = get_effective_table(config, "tailscale", legacy_root_fallback=False)
    tailscale_command = as_str(tailscale_cfg.get("command")) or "tailscale"
    tailscale_lookup = get_tailscale_lookup_safe(command=tailscale_command)

    target_hostname = as_str(getattr(args, "hostname", "")).lower()
    candidates_with_method: list[tuple[str, Any]] = []
    for _, row in nodes_df.iterrows():
        hostname = as_str(row.get("hostname")).strip()
        if not hostname:
            continue

        if parse_bool(row.get("skip_tailscale"), default=False):
            continue

        method = _normalize_method(row.get("tailscale_install_method"))
        if not method:
            continue
        candidates_with_method.append((hostname, row))

    disconnected_candidates: list[tuple[str, Any]] = []
    for hostname, row in candidates_with_method:
        if is_on_tailnet(node_name=hostname, lookup=tailscale_lookup):
            continue
        disconnected_candidates.append((hostname, row))

    if target_hostname:
        disconnected_candidates = [
            (hostname, row)
            for hostname, row in disconnected_candidates
            if hostname.lower() == target_hostname
        ]
    else:
        selected = _select_disconnected_node(disconnected_candidates)
        if selected is None:
            if disconnected_candidates:
                logger.info("No node selected. Exiting.")
                return 0
            logger.info(
                "No disconnected nodes found (all nodes with tailscale_install_method appear on Tailnet)"
            )
            return 0
        disconnected_candidates = [
            (hostname, row)
            for hostname, row in disconnected_candidates
            if hostname.lower() == selected.lower()
        ]

    if target_hostname and not disconnected_candidates:
        logger.error(
            (
                "Hostname '%s' not found in the disconnected set "
                "(requires non-empty tailscale_install_method and not on Tailnet)"
            ),
            target_hostname,
        )
        return 1

    if not disconnected_candidates:
        logger.info("No disconnected nodes found")
        return 0

    failures = 0
    for hostname, row in disconnected_candidates:
        method = _normalize_method(row.get("tailscale_install_method"))

        if method == TAILSCALE_INSTALL_SCRIPT_METHOD:
            ok = _run_direct_tailscale_install(
                hostname=hostname,
                row=row,
                resolver=resolver,
                config_path=config_path,
                args=args,
            )
        elif method == PROXMOX_HELPER_SCRIPT_METHOD:
            ok = _run_proxmox_helper_install(
                hostname=hostname,
                row=row,
                resolver=resolver,
                config_path=config_path,
                args=args,
            )
        else:
            logger.warning(
                (
                    "%s: unsupported tailscale_install_method '%s' "
                    "(expected 'Tailscale Install Script' or 'Proxmox Helper Script')"
                ),
                hostname,
                as_str(row.get("tailscale_install_method")),
            )
            continue

        if not ok:
            failures += 1

    return 1 if failures else 0
