"""Update command — update nodes and services with per-node human approval.

Update methods are auto-detected from the Nodes sheet:
  1. Explicit ``Update Method`` column overrides everything.
  2. ``Script URL`` set → ``pve-helper`` (SSH into container, run built-in update script).
  3. ``Playbooks`` column contains ``services`` or ``docker-compose`` → ``docker-compose``.
  4. ``Managed = true`` → ``apt`` (Ansible apt dist-upgrade).
  5. Otherwise → ``unknown`` (skipped with a warning).

Only nodes with ``Update = true`` (or ``yes`` / ``1``) are included.

The ``Update Method`` column also accepts these override values:
  - ``apt``
  - ``docker-compose``
  - ``pve-helper`` or ``pve-helper:/path/to/script``
  - ``ansible:<playbook.yaml>``
"""

from __future__ import annotations

import argparse
import curses
import logging
import os
import shlex
import subprocess
from pathlib import Path

import pandas as pd

from .config import (
    get_effective_table,
    load_toml_or_exit,
    resolve_path_relative_to_config,
)
from .resolver import build_resolver
from .sheets import (
    as_str,
    configure_sheet_csv_retention,
    df_with_normalized_columns,
    get_sheet_df,
)
from .ssh import (
    require_command,
    ssh_base_args,
    ssh_control_path,
    ssh_start_master,
    ssh_stop_master,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Method detection
# ---------------------------------------------------------------------------

def detect_update_method(row: pd.Series) -> str:
    """Determine the update method for a node row.

    Returns one of: ``pve-helper``, ``pve-helper:<cmd>``, ``docker-compose``,
    ``apt``, ``ansible:<playbook>``, or ``unknown``.
    """
    explicit = as_str(row.get("update_method", "")).strip()
    if explicit:
        return explicit

    script_url = as_str(row.get("script_url", "")).strip()
    if script_url:
        return "pve-helper"

    playbooks_raw = as_str(row.get("playbooks", "")).lower()
    if any(kw in playbooks_raw for kw in ("services", "docker-compose", "docker_compose")):
        return "docker-compose"

    managed = as_str(row.get("managed", "")).lower() in {"true", "yes", "1"}
    if managed:
        return "apt"

    return "unknown"


def build_update_plan(nodes_df: pd.DataFrame) -> list[dict]:
    """Return a list of update-enabled nodes with their detected update methods.

    Each entry is a dict with keys: ``hostname``, ``method``, ``ip_address``,
    ``managed``, ``row``.
    """
    df_norm = df_with_normalized_columns(nodes_df)
    plan: list[dict] = []

    for _, row in df_norm.iterrows():
        hostname = as_str(row.get("hostname", "")).strip()
        if not hostname:
            continue

        update_val = as_str(row.get("update", "")).strip().lower()
        if update_val not in {"true", "yes", "1"}:
            continue

        method = detect_update_method(row)
        ip = as_str(row.get("ip_address", "")).strip()
        managed = as_str(row.get("managed", "")).lower() in {"true", "yes", "1"}

        plan.append({
            "hostname": hostname,
            "method": method,
            "ip_address": ip,
            "managed": managed,
            "row": row,
        })

    plan.sort(key=lambda x: x["hostname"])
    return plan


# ---------------------------------------------------------------------------
# Multi-select curses menu
# ---------------------------------------------------------------------------

def _curses_multi_select(
    stdscr: "curses._CursesWindow",  # type: ignore[name-defined]
    entries: list[dict],
) -> list[dict] | None:
    """Interactive multi-select menu.

    Controls:
      ↑/↓ — navigate
      Space — toggle selected item
      a — toggle all / none
      Enter — confirm selection
      q / Esc — abort
    """
    curses.curs_set(0)
    selected_idx = 0
    checked: set[int] = set(range(len(entries)))  # all selected by default

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Header
        stdscr.addstr(0, 0, "═" * min(width - 1, 80))
        stdscr.addstr(1, 0, "  SELECT NODES TO UPDATE")
        stdscr.addstr(2, 0, "═" * min(width - 1, 80))
        stdscr.addstr(3, 0, "  ↑/↓=navigate  Space=toggle  a=all/none  Enter=proceed  q=quit")
        stdscr.addstr(4, 0, "─" * min(width - 1, 80))

        # "All" toggle row (index 0 in navigation)
        all_checked = len(checked) == len(entries)
        all_marker = "[×]" if all_checked else "[ ]"
        all_prefix = "▶" if selected_idx == 0 else " "
        try:
            stdscr.addstr(5, 0, f"{all_prefix} {all_marker} ALL  ({len(entries)} nodes)")
        except curses.error:
            pass

        # Node rows (navigation index = i + 1)
        for i, entry in enumerate(entries):
            y = 6 + i
            if y >= height - 2:
                break
            marker = "[×]" if i in checked else "[ ]"
            prefix = "▶" if selected_idx == i + 1 else " "
            method_label = entry["method"].upper().replace("-", " ")
            label = f"{prefix} {marker} {entry['hostname'].ljust(26)} {method_label}"
            try:
                stdscr.addstr(y, 0, label[: width - 1])
            except curses.error:
                pass

        # Footer
        count = len(checked)
        footer = f"  {count} of {len(entries)} selected — press Enter to proceed"
        footer_y = min(height - 1, 6 + len(entries) + 1)
        try:
            stdscr.addstr(footer_y, 0, footer[: width - 1])
        except curses.error:
            pass

        stdscr.refresh()

        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            return None

        num_rows = len(entries) + 1  # +1 for the "All" row

        if ch in (ord("q"), ord("Q"), 27):  # q, Q, ESC
            return None
        elif ch == curses.KEY_UP:
            selected_idx = (selected_idx - 1) % num_rows
        elif ch == curses.KEY_DOWN:
            selected_idx = (selected_idx + 1) % num_rows
        elif ch == ord(" "):
            if selected_idx == 0:
                if all_checked:
                    checked.clear()
                else:
                    checked = set(range(len(entries)))
            else:
                i = selected_idx - 1
                if i in checked:
                    checked.discard(i)
                else:
                    checked.add(i)
        elif ch == ord("a"):
            if all_checked:
                checked.clear()
            else:
                checked = set(range(len(entries)))
        elif ch in (10, 13, curses.KEY_ENTER):
            if not checked:
                continue  # require at least one selection
            return [entries[i] for i in sorted(checked)]

    return None  # unreachable, satisfies type checker


# ---------------------------------------------------------------------------
# Per-node approval
# ---------------------------------------------------------------------------

def _approve_node(node: dict) -> str:
    """Prompt for approval of a single node update.

    Returns one of: ``'y'`` (approve), ``'s'`` (skip this node),
    ``'q'`` (quit — stop processing remaining nodes).
    """
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  Node:    {node['hostname']}")
    print(f"  IP:      {node['ip_address'] or '(unknown)'}")
    print(f"  Method:  {node['method']}")
    print(sep)

    while True:
        try:
            answer = input("  Approve update? [y/N/s(skip)/q(quit all)] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "q"

        if answer in ("y", "yes"):
            return "y"
        elif answer in ("s", "skip"):
            return "s"
        elif answer in ("q", "quit"):
            return "q"
        elif answer in ("n", "no", ""):
            return "s"
        else:
            print("  Please enter y, s, or q.")


# ---------------------------------------------------------------------------
# Update execution helpers
# ---------------------------------------------------------------------------

def _run_ansible_playbook(
    hostname: str,
    playbook: str,
    settings: dict,
    config_path: Path,
) -> bool:
    """Run a single Ansible playbook against a specific hostname."""
    repo_root = Path(__file__).resolve().parents[1]
    ansible_dir = repo_root / "ansible"
    inventory_script = ansible_dir / "inventory" / "inventory-spreadsheet.py"
    playbook_path = ansible_dir / "playbooks" / playbook

    if not playbook_path.exists():
        logger.error("Playbook not found: %s", playbook_path)
        return False

    apply = bool(settings.get("apply", False))

    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(ansible_dir / "ansible.cfg")

    cmd = [
        "ansible-playbook",
        "-i", str(inventory_script),
        "--limit", hostname,
        str(playbook_path),
    ]

    logger.info("Running: %s", " ".join(shlex.quote(str(c)) for c in cmd))

    if not apply:
        print("  Dry run (--apply not set): no remote changes made")
        print(f"  Would run: {' '.join(shlex.quote(str(c)) for c in cmd)}")
        return True

    try:
        subprocess.run(cmd, env=env, check=True)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("Playbook %s failed for %s: %s", playbook, hostname, exc)
        return False


def _run_apt_update(node: dict, settings: dict, config_path: Path) -> bool:
    """Run the apt dist-upgrade playbook on a managed node."""
    hostname = node["hostname"]
    print(f"  Running APT dist-upgrade on {hostname}...")
    return _run_ansible_playbook(hostname, "update-apt.yaml", settings, config_path)


def _run_docker_compose_update(node: dict, settings: dict, config_path: Path) -> bool:
    """Pull updated images and restart Docker Compose services on a managed node."""
    hostname = node["hostname"]
    print(f"  Pulling and restarting Docker Compose services on {hostname}...")
    return _run_ansible_playbook(hostname, "update-docker-compose.yaml", settings, config_path)


def _run_pve_helper_update(
    node: dict,
    settings: dict,
    config_path: Path,
    resolver,
) -> bool:
    """SSH into a PVE container and run its built-in update script."""
    hostname = node["hostname"]
    apply = bool(settings.get("apply", False))

    # Determine which update command to run inside the container.
    # Method column may be "pve-helper" or "pve-helper:/path/to/script".
    method_raw = node.get("method", "pve-helper")
    default_cmd = settings.get("pve_update_cmd", "update")
    if ":" in method_raw:
        update_cmd = method_raw.split(":", 1)[1].strip() or default_cmd
    else:
        update_cmd = default_cmd

    # SSH connection parameters.
    managed = node.get("managed", False)
    ssh_user = str(settings.get("pve_ssh_user", "") or ("ansible" if managed else "root"))
    ssh_port = int(settings.get("pve_ssh_port", settings.get("ssh_port", 22)))

    identity_raw = str(
        settings.get("pve_ssh_identity_file", settings.get("ssh_identity_file", "")) or ""
    ).strip()
    identity_file: Path | None = None
    if identity_raw:
        identity_file = resolve_path_relative_to_config(config_path, identity_raw)
        if not identity_file.exists():
            logger.error("SSH identity file not found: %s", identity_file)
            return False

    # Resolve the container's IP/hostname.
    target_host: str
    if resolver is not None:
        target_host = resolver.resolve(hostname)
    else:
        target_host = node.get("ip_address") or hostname

    ssh_target = f"{ssh_user}@{target_host}"

    if not apply:
        print("  Dry run (--apply not set): no remote changes made")
        print(f"  Would SSH: {ssh_target} (port {ssh_port})")
        print(f"  Would run: {update_cmd}")
        return True

    require_command("ssh")
    print(f"  SSHing to {ssh_target} (port {ssh_port}) → running: {update_cmd}")

    control_path = ssh_control_path(
        prefix="homelab-update",
        username=ssh_user,
        host=target_host,
        port=ssh_port,
    )
    base_args = ssh_base_args(
        control_path=control_path,
        port=ssh_port,
        identity_file=identity_file,
    )

    try:
        ssh_start_master(ssh_args=base_args, target=ssh_target, env=None)
    except subprocess.CalledProcessError as exc:
        logger.error("Could not open SSH connection to %s: %s", ssh_target, exc)
        return False

    try:
        result = subprocess.run(
            [*base_args, ssh_target, update_cmd],
            check=False,
        )
        if result.returncode != 0:
            logger.error(
                "Update command exited with code %d on %s", result.returncode, hostname
            )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("SSH update failed for %s: %s", hostname, exc)
        return False
    finally:
        ssh_stop_master(ssh_args=base_args, target=ssh_target, env=None)


def _execute_update(
    node: dict,
    settings: dict,
    config_path: Path,
    resolver,
) -> bool:
    """Dispatch an update to the correct handler based on the detected method."""
    method = node["method"]

    if method == "apt":
        return _run_apt_update(node, settings, config_path)
    elif method == "docker-compose":
        return _run_docker_compose_update(node, settings, config_path)
    elif method.startswith("pve-helper"):
        return _run_pve_helper_update(node, settings, config_path, resolver)
    elif method.startswith("ansible:"):
        playbook = method.split(":", 1)[1].strip()
        if not playbook:
            logger.error(
                "No playbook specified in 'ansible:' method for %s", node["hostname"]
            )
            return False
        return _run_ansible_playbook(node["hostname"], playbook, settings, config_path)
    elif method == "unknown":
        logger.warning(
            "No update method could be detected for %s — skipping. "
            "Set the 'Update Method' column or ensure Managed/Script URL is set.",
            node["hostname"],
        )
        return False
    else:
        logger.error("Unrecognised update method '%s' for %s", method, node["hostname"])
        return False


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="homelab update",
        description="Update nodes and services with per-node human approval.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=Path.cwd().resolve() / "config.toml",
        help="Path to TOML configuration file",
    )
    parser.add_argument("--_apply", dest="apply", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_debug", dest="debug", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_keep", dest="keep", action="store_true", help=argparse.SUPPRESS)
    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Run the interactive update workflow."""
    parser = _build_parser()
    args = parser.parse_args(argv or [])

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

    config_path = args.config.resolve()
    config_dict = load_toml_or_exit(config_path)

    settings = dict(get_effective_table(config_dict, "update", inherit=("globals",)))
    settings["apply"] = bool(getattr(args, "apply", False))

    keep_downloads = bool(getattr(args, "keep", False)) or bool(settings.get("keep", False))
    configure_sheet_csv_retention(keep=keep_downloads)

    sheet_url = settings.get("sheet_url")
    nodes_gid = settings.get("nodes_gid")
    if not sheet_url or not nodes_gid:
        logger.error("Missing sheet_url or nodes_gid in config")
        return 1

    try:
        nodes_df = get_sheet_df(sheet_url, int(nodes_gid), 30.0, "Nodes")
    except Exception as exc:
        logger.error("Error loading Nodes sheet: %s", exc)
        return 1

    resolver = build_resolver(config_dict, nodes_df)

    plan = build_update_plan(nodes_df)

    if not plan:
        print("No nodes with 'Update = true' found in the Nodes sheet.")
        print(
            "Add an 'Update' column to the Nodes tab and tick it for nodes "
            "you want to include in update runs."
        )
        return 0

    # --- Multi-select menu ---
    try:
        selected = curses.wrapper(lambda stdscr: _curses_multi_select(stdscr, plan))
    except KeyboardInterrupt:
        return 0

    if selected is None:
        print("Aborted.")
        return 0

    if not selected:
        print("No nodes selected.")
        return 0

    # --- Per-node approval and execution loop ---
    print(f"\nPreparing to update {len(selected)} node(s)...")

    results: dict[str, str] = {}

    for i, node in enumerate(selected):
        hostname = node["hostname"]
        decision = _approve_node(node)

        if decision == "q":
            print("\n  Stopping. Remaining nodes will be skipped.")
            for remaining in selected[i:]:
                if remaining["hostname"] not in results:
                    results[remaining["hostname"]] = "skipped"
            break
        elif decision == "s":
            print(f"  Skipping {hostname}.")
            results[hostname] = "skipped"
            continue

        print(f"  Updating {hostname}...")
        ok = _execute_update(node, settings, config_path, resolver)
        results[hostname] = "ok" if ok else "failed"

        if ok:
            print(f"  ✓ {hostname} — done.")
        else:
            print(f"  ✗ {hostname} — failed. See output above.")

    # --- Summary ---
    ok_count = sum(1 for v in results.values() if v == "ok")
    failed_count = sum(1 for v in results.values() if v == "failed")
    skipped_count = sum(1 for v in results.values() if v == "skipped")

    print(f"\n{'═' * 60}")
    print(f"  Update Summary: {ok_count} ok, {failed_count} failed, {skipped_count} skipped")
    print(f"{'─' * 60}")
    for hostname, status in results.items():
        marker = "✓" if status == "ok" else ("✗" if status == "failed" else "–")
        print(f"  {marker}  {hostname:<28} {status}")
    print(f"{'═' * 60}")

    return 1 if failed_count > 0 else 0
