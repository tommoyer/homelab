from __future__ import annotations

import argparse
import ipaddress
import logging
import os
import re
import shlex
import subprocess
import sys
import curses
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import (
    get_effective_table,
    load_toml_or_exit,
    render_jinja_template,
    resolve_path_relative_to_config,
)
from .resolver import HostResolver, build_resolver
from .sheets import (
    get_sheet_df,
    as_str,
    build_sheet_url,
    df_with_normalized_columns,
    load_nodes_lookup,
)
from .ssh import prefix_sshpass, require_command, sshpass_env_from_password_env

logger = logging.getLogger(__name__)


def run_ansible_playbooks(hostname: str, config_path: Path, extra_playbooks: list[str] | None = None) -> bool:
    """
    Run bootstrap.yaml, hardening.yaml, and any additional playbooks for the given hostname.
    
    Args:
        hostname: Target hostname to limit ansible execution
        config_path: Path to config file (for environment setup)
        extra_playbooks: Optional list of additional playbook names to run after bootstrap and hardening
        
    Returns:
        True if all playbooks succeed, False otherwise
    """
    repo_root = Path(__file__).resolve().parents[1]
    ansible_dir = repo_root / "ansible"
    inventory_script = ansible_dir / "inventory" / "inventory-spreadsheet.py"
    playbooks = ["bootstrap.yaml", "hardening.yaml"]
    
    # Append extra playbooks if provided
    if extra_playbooks:
        playbooks.extend(extra_playbooks)
    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(ansible_dir / "ansible.cfg")
    success = True
    for playbook in playbooks:
        playbook_path = ansible_dir / "playbooks" / playbook
        if not playbook_path.exists():
            logger.error(f"Playbook not found: {playbook_path}")
            return False
        cmd = [
            "ansible-playbook",
            "-i", str(inventory_script),
            "--limit", hostname,
            str(playbook_path),
        ]
        logger.info(f"Running: {' '.join(shlex.quote(str(c)) for c in cmd)}")
        try:
            result = subprocess.run(cmd, env=env, check=True)
        except subprocess.CalledProcessError as exc:
            logger.error(f"Ansible playbook failed: {playbook} for {hostname}: {exc}")
            success = False
    return success


def _normalize_int_like_string(value: object) -> str:
    """Normalize values that should be integers but may arrive as floats/strings.

    Examples:
      - 20.0 -> "20"
      - "20.0" -> "20"
      - " 20 " -> "20"
    """

    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip()

    cleaned = str(value).strip()
    if not cleaned:
        return ""
    # Common pandas CSV case: integer column becomes float-like string.
    m = re.match(r"^(\d+)\.0+$", cleaned)
    if m:
        return m.group(1)
    return cleaned



def _parse_playbooks_value(value: object) -> list[str]:
    """
    Parse a comma-separated Playbooks cell into a list of playbook names.
    
    Args:
        value: Raw value from Nodes sheet Playbooks column
        
    Returns:
        List of playbook names (stripped, non-empty)
        
    Example:
        "app.yaml, monitoring.yaml" -> ["app.yaml", "monitoring.yaml"]
        "" -> []
        None -> []
    """
    import pandas as pd
    
    if not value or (isinstance(value, float) and pd.isna(value)):
        return []
    
    playbooks_str = str(value).strip()
    if not playbooks_str:
        return []
    
    return [p.strip() for p in playbooks_str.split(",") if p.strip()]



def _select_deployable_node(nodes_df: pd.DataFrame) -> str | None:
    """
    Present an interactive curses menu of deployable nodes.
    
    A node is deployable if:
    - Managed is true, OR
    - Script URL is set
    
    Returns:
        Selected hostname, or None if user cancels
    """
    df_norm = df_with_normalized_columns(nodes_df)
    
    # Find deployable nodes
    deployable = []
    for _, row in df_norm.iterrows():
        hostname = as_str(row.get("hostname", "")).strip()
        if not hostname:
            continue
            
        managed = as_str(row.get("managed", "")).lower() in {"true", "yes", "1"}
        script_url = as_str(row.get("script_url", "")).strip()
        
        if managed or script_url:
            # Build deployment type label
            parts = []
            if script_url:
                parts.append("Helper")
            if managed:
                parts.append("Ansible")
            deploy_type = " + ".join(parts)
            
            deployable.append({
                "hostname": hostname,
                "deploy_type": deploy_type,
            })
    
    if not deployable:
        print("No deployable nodes found (need Managed=true or Script URL set).", file=sys.stderr)
        return None
    
    # Sort by hostname
    deployable.sort(key=lambda x: x["hostname"])
    
    # Use curses for menu
    def _curses_menu(stdscr: "curses._CursesWindow") -> str | None:  # type: ignore[name-defined]
        """Display curses menu and return selected hostname."""
        curses.curs_set(0)
        selected = 0
        
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            
            # Header
            stdscr.addstr(0, 0, "=" * min(width - 1, 80))
            stdscr.addstr(1, 0, "  SELECT NODE TO DEPLOY")
            stdscr.addstr(2, 0, "=" * min(width - 1, 80))
            stdscr.addstr(3, 0, "Use ↑/↓ to select, Enter to deploy, q to quit")
            stdscr.addstr(4, 0, "-" * min(width - 1, 80))
            
            # Menu items
            for idx, node in enumerate(deployable):
                prefix = "▶" if idx == selected else " "
                label = f"{prefix} {node['hostname'].ljust(20)} [{node['deploy_type']}]"
                y_pos = 6 + idx
                if y_pos < height - 1:
                    try:
                        stdscr.addstr(y_pos, 0, label[: width - 1])
                    except curses.error:
                        pass  # Ignore if we run out of screen space
            
            # Get input
            try:
                ch = stdscr.getch()
            except KeyboardInterrupt:
                return None
            
            if ch in (ord("q"), ord("Q"), 27):  # q, Q, or ESC
                return None
            elif ch == curses.KEY_UP:
                selected = (selected - 1) % len(deployable)
            elif ch == curses.KEY_DOWN:
                selected = (selected + 1) % len(deployable)
            elif ch in (10, 13, curses.KEY_ENTER):  # Enter
                return deployable[selected]["hostname"]
    
    try:
        return curses.wrapper(_curses_menu)
    except KeyboardInterrupt:
        return None



def _add_parser_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "hostname",
        nargs="?",
        default=None,
        help="Hostname of the new node to deploy (if omitted, displays interactive menu)",
    )
    # Global overrides
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=Path.cwd().resolve() / "config.toml",
        help="Path to an alternative TOML configuration file",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply changes to the Proxmox node over SSH (sync defaults + run the helper script). "
            "Without --apply, performs a dry run: renders templates locally and prints what would be executed."
        ),
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging to see detailed execution information",
    )

    parser.add_argument(
        "--render-dir",
        type=Path,
        default=None,
        help=(
            "Directory to write rendered service defaults during dry-run. "
            "Defaults to <repo>/pve-scripts/rendered/<hostname>/"
        ),
    )

    parser.add_argument(
        "--bridge",
        default="vmbr0",
        help=(
            "Proxmox bridge to use for pve-script var_brg. "
            "Defaults to vmbr0. (The Nodes sheet 'Interface' column is the guest NIC, not the PVE bridge.)"
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="homelab deploy",
        description="Reads Google Sheets config to run a Proxmox VE Helper Script.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_parser_arguments(parser)
    return parser


def setup_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "deploy",
        help="Deploy a PVE Helper Script",
        description="Reads Google Sheets config to run a Proxmox VE Helper Script.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_parser_arguments(parser)


def get_node_config(df: pd.DataFrame, hostname: str) -> dict:
    df_norm = df_with_normalized_columns(df)
    if "hostname" not in df_norm.columns:
        raise ValueError("Nodes sheet is missing a 'Hostname' column")

    target = (hostname or "").strip().lower()
    node_df = df_norm[df_norm["hostname"].astype(str).str.strip().str.lower() == target]
    if node_df.empty:
        raise ValueError(f"Hostname '{hostname}' not found in Nodes sheet.")

    row = node_df.iloc[0]

    script_url = as_str(row.get("script_url"))
    template_raw = as_str(row.get("configuration_template"))
    script_id = normalize_template_id(template_raw) or None

    # Backward-compatible fallbacks if Configuration Template is not present.
    if not script_id:
        script_id = normalize_template_id(as_str(row.get("script_id"))) or None
    if not script_id:
        script_id = normalize_template_id(as_str(row.get("service"))) or None
    if not script_id:
        script_id = normalize_template_id(as_str(row.get("helper_script"))) or None

    if not script_id and script_url:
        script_id = infer_script_id_from_url(script_url)

    node_data = build_node_template_data(row)

    proxmox_node = as_str(row.get("proxmox_node"))

    # Allow per-row override of the PVE node/host to execute against.
    settings_override = {}
    if proxmox_node:
        settings_override["proxmox_host"] = proxmox_node

    return {
        "hostname": hostname,
        "script_url": script_url or None,
        "script_id": script_id,
        "node": node_data,
        "settings_override": settings_override,
    }


def normalize_template_id(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    name = Path(raw).name
    for suffix in (".vars.j2", ".vars.jinja2", ".vars.jinja", ".j2", ".jinja2", ".jinja", ".vars"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    name = name.strip()
    return name or None


def _parse_prefixlen(value: str) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        try:
            v = int(raw)
        except ValueError:
            return None
        return v if 0 <= v <= 128 else None
    # net like 192.168.10.0/24
    if "/" in raw:
        try:
            return int(ipaddress.ip_network(raw, strict=False).prefixlen)
        except Exception:
            return None
    # netmask like 255.255.255.0
    if "." in raw:
        try:
            return int(ipaddress.ip_interface(f"0.0.0.0/{raw}").network.prefixlen)
        except Exception:
            return None
    return None


def build_node_template_data(row: pd.Series) -> dict:
    """Build a stable template context from a normalized Nodes sheet row."""

    hostname = as_str(row.get("hostname"))
    dns_name = as_str(row.get("dns_name"))
    ip_raw = as_str(row.get("ip_address"))
    subnet_raw = as_str(row.get("subnet"))
    static_dhcp = as_str(row.get("static_dhcp")).lower()
    interface = as_str(row.get("interface"))
    mac = as_str(row.get("mac_address"))

    vlan_id = _normalize_int_like_string(row.get("vlan_id"))

    # These aren't in your provided sheet headers, but we keep them as optional
    # keys so templates can reference them without StrictUndefined errors.
    gateway = as_str(row.get("gateway"))
    vlan = _normalize_int_like_string(row.get("vlan"))
    # Per-host DNS server (sheet column "DNS Server").
    ns = as_str(row.get("dns_server"))

    # Prefer the explicit sheet column "VLAN ID".
    if vlan_id:
        vlan = vlan_id

    # Gateway is derived from VLAN ID per convention.
    if vlan and vlan.isdigit():
        gateway = f"192.168.{int(vlan)}.1"

    searchdomain = as_str(row.get("searchdomain", row.get("search_domain", row.get("domain", ""))))
    if not searchdomain and dns_name and "." in dns_name:
        searchdomain = dns_name.split(".", 1)[1]

    # var_net expects either 'dhcp' or 'IP/prefix'.
    net = ""
    if static_dhcp in {"dhcp", "dynamic"} or ip_raw.lower() in {"dhcp", "dhcp4", "dhcp6"}:
        net = "dhcp"
    elif "/" in ip_raw:
        net = ip_raw
    elif ip_raw:
        prefixlen = _parse_prefixlen(subnet_raw)
        if prefixlen is not None:
            net = f"{ip_raw}/{prefixlen}"
        else:
            net = ip_raw

    # Best-effort inference for gateway from subnet if unset and VLAN ID isn't present.
    if not gateway and subnet_raw and ip_raw and ip_raw.lower() not in {"dhcp", "dhcp4", "dhcp6"}:
        try:
            if "/" in subnet_raw:
                network = ipaddress.ip_network(subnet_raw, strict=False)
            else:
                prefixlen = _parse_prefixlen(subnet_raw)
                network = ipaddress.ip_network(f"{ip_raw}/{prefixlen}", strict=False) if prefixlen is not None else None

            if isinstance(network, ipaddress.IPv4Network) and network.prefixlen <= 30:
                gateway = str(ipaddress.ip_address(int(network.network_address) + 1))
        except Exception:
            pass

    # Best-effort inference for vlan from common RFC1918 addressing scheme.
    if not vlan:
        ip_for_vlan = ""
        if ip_raw and ip_raw.lower() not in {"dhcp", "dhcp4", "dhcp6"}:
            ip_for_vlan = ip_raw.split("/", 1)[0]
        elif subnet_raw and "/" in subnet_raw:
            ip_for_vlan = subnet_raw.split("/", 1)[0]
        if ip_for_vlan.startswith("192.168."):
            parts = ip_for_vlan.split(".")
            if len(parts) >= 3 and parts[2].isdigit():
                vlan_guess = int(parts[2])
                if 1 <= vlan_guess <= 4094:
                    vlan = str(vlan_guess)

    return {
        "hostname": hostname,
        "dns_name": dns_name,
        "ip": ip_raw,
        "net": net,
        "gateway": gateway,
        "vlan": vlan,
        "bridge": "",
        "interface": interface,
        "ns": ns,
        "mac": mac,
        "searchdomain": searchdomain,
    }


def infer_script_id_from_url(script_url: str) -> str | None:
    """Infer a ProxmoxVE Community Scripts 'id' from a helper script URL.

    Supports URLs like:
      - https://community-scripts.github.io/ProxmoxVE/scripts?id=pihole
      - https://community-scripts.github.io/ProxmoxVE/scripts?id=docker&category=...
    Falls back to using the last path segment (minus common extensions).
    """

    try:
        parsed = urllib.parse.urlparse(str(script_url))
    except Exception:
        return None

    qs = urllib.parse.parse_qs(parsed.query)
    if "id" in qs and qs["id"]:
        val = str(qs["id"][0]).strip()
        return val or None

    # Fallback: last path component without extension.
    name = Path(parsed.path).name
    for suffix in (".sh", ".bash"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name or None


def _build_ssh_scp_env_and_user(
    *,
    settings: dict,
    config_path: Path,
    apply: bool,
    nodes_lookup: dict[str, str] | None = None,
) -> tuple[int, Path | None, dict[str, str] | None, bool, str, str]:
    host = settings.get("proxmox_host")
    user = settings.get("proxmox_user")
    ssh_port = int(settings.get("proxmox_ssh_port", settings.get("ssh_port", 22)))

    identity_raw = str(settings.get("proxmox_ssh_identity_file", settings.get("ssh_identity_file", "")) or "").strip()
    identity_file = resolve_path_relative_to_config(config_path, identity_raw) if identity_raw else None
    if identity_file is not None and not identity_file.exists():
        raise FileNotFoundError(f"SSH identity file not found: {identity_file}")

    password_env = str(settings.get("proxmox_password_env", settings.get("password_env", "")) or "").strip() or None
    use_sshpass = bool(password_env)

    env = None
    if apply:
        require_command("ssh")
        require_command("scp")
        if use_sshpass:
            require_command("sshpass")
            env = sshpass_env_from_password_env(password_env=password_env)

    ssh_host = str(host)
    ssh_host = _resolve_node_shortname_to_ip(ssh_host, nodes_lookup)
    ssh_user = str(user).split("@")[0]  # 'root@pam' -> 'root'
    return ssh_port, identity_file, env, use_sshpass, ssh_user, ssh_host


def _resolve_node_shortname_to_ip(host: str, nodes_lookup: dict[str, str] | None) -> str:
    """Resolve a short hostname using the Nodes sheet lookup.

    If the host already looks like an IP or FQDN, it is returned unchanged.

    .. note:: When a :class:`~homelab.resolver.HostResolver` is available
       (stashed under the ``_resolver`` key of *nodes_lookup*), it is used
       instead so that Tailscale-first resolution is transparent.
    """
    raw = str(host or "").strip()
    if not raw:
        return raw

    # If a HostResolver was stashed by the caller, delegate to it.
    if isinstance(nodes_lookup, dict) and "_resolver" in nodes_lookup:
        resolver: HostResolver = nodes_lookup["_resolver"]  # type: ignore[assignment]
        return resolver.resolve(raw)

    if nodes_lookup is None:
        return raw

    # If it's already an IP address, keep it.
    try:
        ipaddress.ip_address(raw)
        return raw
    except Exception:
        pass

    # If it's already an FQDN, keep it.
    if "." in raw:
        return raw

    ip = nodes_lookup.get(raw.lower())
    if not ip:
        return raw
    logger.debug("Resolved Proxmox node shortname '%s' -> %s", raw, ip)
    return ip


def _sync_pve_helper_defaults(
    *,
    node_cfg: dict,
    settings: dict,
    config_path: Path,
    apply: bool,
    render_dir: Path | None,
    nodes_lookup: dict[str, str] | None = None,
) -> bool:
    """Copy defaults and per-service defaults to the PVE node.

    - Copies repo pve-scripts/defaults.vars -> /usr/local/community-scripts/defaults.vars
    - Renders repo pve-scripts/<script_id>.vars.j2 -> /usr/local/community-scripts/defaults/<script_id>.vars
    """

    script_id = node_cfg.get("script_id")
    if not script_id:
        logger.error(
            "Unable to determine script id for %s (needed to pick a pve-scripts/*.vars.j2 template)",
            node_cfg.get("hostname"),
        )
        return False

    repo_root = Path(__file__).resolve().parents[1]
    templates_dir = repo_root / "templates" / "pve-scripts"
    default_generated_dir = repo_root / "generated" / "pve-scripts"
    local_defaults_vars = templates_dir / "defaults.vars"
    local_service_template = templates_dir / f"{script_id}.vars.j2"

    if not local_defaults_vars.exists():
        logger.error("Missing local defaults vars file: %s", local_defaults_vars)
        return False
    if not local_service_template.exists():
        logger.error("Missing local service vars template: %s", local_service_template)
        return False

    try:
        ssh_port, identity_file, env, use_sshpass, ssh_user, ssh_host = _build_ssh_scp_env_and_user(
            settings=settings,
            config_path=config_path,
            apply=apply,
            nodes_lookup=nodes_lookup,
        )
    except Exception as exc:
        logger.error(str(exc))
        return False

    ssh_target = f"{ssh_user}@{ssh_host}"

    common_ssh_opts = [
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-p",
        str(ssh_port),
    ]
    ssh_cmd_base = ["ssh", *common_ssh_opts]
    scp_cmd_base = [
        "scp",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-P",
        str(ssh_port),
    ]
    if identity_file is not None:
        ssh_cmd_base.extend(["-i", str(identity_file)])
        scp_cmd_base.extend(["-i", str(identity_file)])

    remote_defaults_vars = "/usr/local/community-scripts/defaults.vars"
    remote_defaults_dir = "/usr/local/community-scripts/defaults"
    remote_service_vars = f"{remote_defaults_dir}/{script_id}.vars"

    logger.info("Syncing PVE community-scripts defaults to %s", ssh_target)

    ssh_authorized_key = as_str(settings.get("ssh_authorized_key"))
    ssh_authorized_key_file = as_str(settings.get("ssh_authorized_key_file"))
    if not ssh_authorized_key and ssh_authorized_key_file:
        try:
            key_path = resolve_path_relative_to_config(config_path, ssh_authorized_key_file)
            ssh_authorized_key = key_path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            logger.error(
                "Failed to read ssh_authorized_key_file '%s': %s",
                ssh_authorized_key_file,
                exc,
            )
            return False

    # Render per-service defaults (always, so dry-run can write it locally).
    try:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rendered = render_jinja_template(
            template_path=local_service_template,
            context={
                "generated_at": generated_at,
                "script_id": script_id,
                "node": node_cfg.get("node", {}),
                "ssh_authorized_key": ssh_authorized_key,
            },
        )
    except Exception as exc:
        logger.error("Failed to render %s: %s", local_service_template, exc)
        return False

    # Always write the rendered vars file locally so it's easy to inspect, and so apply
    # mode uploads the exact same content that was rendered.
    out_dir = render_dir
    if out_dir is None:
        # Check for config-specified render_dir before falling back to default.
        config_render_dir = settings.get("render_dir")
        if config_render_dir:
            out_dir = resolve_path_relative_to_config(config_path, str(config_render_dir))
            node_name = as_str(node_cfg.get("hostname")) or "unknown"
            out_dir = out_dir / node_name
        else:
            node_name = as_str(node_cfg.get("hostname")) or "unknown"
            out_dir = default_generated_dir / node_name
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        local_rendered_path = out_dir / f"{script_id}.vars"
        local_rendered_path.write_text(rendered, encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to write rendered vars file: %s", exc)
        return False

    if not apply:
        # Dry-run: print planned remote actions.
        print("Dry run (no --apply): no remote changes made")
        print("- step: sync PVE community-scripts defaults")
        print(f"- generated: {local_rendered_path}")
        print(f"- would ssh: {ssh_target} mkdir -p {remote_defaults_dir}")
        print(f"- would scp: {local_defaults_vars} -> {ssh_target}:{remote_defaults_vars}")
        print(f"- would scp: {local_rendered_path} -> {ssh_target}:{remote_service_vars}")
        return True

    # Apply mode: Ensure destination directories exist.
    mkdir_cmd = [*ssh_cmd_base, ssh_target, f"mkdir -p {shlex.quote(remote_defaults_dir)}"]
    mkdir_cmd = prefix_sshpass(mkdir_cmd, enabled=use_sshpass)
    try:
        subprocess.run(mkdir_cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to create remote defaults dir: %s", exc)
        return False

    # Copy defaults.vars.
    scp_defaults_cmd = [
        *scp_cmd_base,
        str(local_defaults_vars),
        f"{ssh_target}:{remote_defaults_vars}",
    ]
    scp_defaults_cmd = prefix_sshpass(scp_defaults_cmd, enabled=use_sshpass)
    try:
        subprocess.run(scp_defaults_cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to copy defaults.vars to PVE node: %s", exc)
        return False

    # Copy per-service defaults (use the locally-rendered file).
    try:
        scp_service_cmd = [
            *scp_cmd_base,
            str(local_rendered_path),
            f"{ssh_target}:{remote_service_vars}",
        ]
        scp_service_cmd = prefix_sshpass(scp_service_cmd, enabled=use_sshpass)
        subprocess.run(scp_service_cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to copy service defaults to PVE node: %s", exc)
        return False

    logger.info("Synced defaults: %s and %s", remote_defaults_vars, remote_service_vars)
    return True


def run_proxmox_helper_script(
    *,
    node_cfg: dict,
    settings: dict,
    config_path: Path,
    nodes_lookup: dict[str, str] | None = None,
) -> bool:
    script_url = node_cfg.get("script_url")
    if not script_url:
        return True  # Nothing to do, returning success

    effective_settings = dict(settings)
    overrides = node_cfg.get("settings_override") or {}
    if isinstance(overrides, dict) and overrides:
        effective_settings.update(overrides)

    # Build the full URL using pve_scripts_base_url from config if script_url is not absolute
    from urllib.parse import urljoin, urlparse
    base_url = effective_settings.get("pve_scripts_base_url")
    parsed = urlparse(str(script_url))
    if base_url and not parsed.scheme:
        # If script_url is a relative path, join with base_url
        full_script_url = urljoin(base_url, script_url)
    else:
        full_script_url = script_url

    apply = bool(effective_settings.get("apply", False))
    render_dir_raw = effective_settings.get("render_dir")
    render_dir: Path | None = Path(render_dir_raw) if render_dir_raw else None

    try:
        ssh_port, identity_file, env, use_sshpass, ssh_user, ssh_host = _build_ssh_scp_env_and_user(
            settings=effective_settings,
            config_path=config_path,
            apply=apply,
            nodes_lookup=nodes_lookup,
        )
    except (RuntimeError, FileNotFoundError) as exc:
        logger.error(str(exc))
        return False

    if not _sync_pve_helper_defaults(
        node_cfg=node_cfg,
        settings=effective_settings,
        config_path=config_path,
        apply=apply,
        render_dir=render_dir,
        nodes_lookup=nodes_lookup,
    ):
        return False

    logger.info("Executing Proxmox Helper script from URL on node %s", ssh_host)
    quoted_url = shlex.quote(str(full_script_url))
    cmd = f"bash -c \"$(wget -qLO - {quoted_url})\""

    logger.info("Command: %s", cmd)

    if not apply:
        target = f"{ssh_user}@{ssh_host}"
        print("Dry run (no --apply): no remote changes made")
        print("- step: run Proxmox helper script")
        print(f"- would ssh: {target} (port {ssh_port}) execute:")
        print(f"  {cmd}")
        print("Re-run with --apply to perform these actions.")
        return True

    # We execute this on the Proxmox host using SSH.

    # Run interactively so the helper script can prompt for input.
    ssh_cmd = [
        "ssh",
        "-t",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-p",
        str(ssh_port),
    ]
    if identity_file is not None:
        ssh_cmd.extend(["-i", str(identity_file)])
    ssh_cmd.extend([f"{ssh_user}@{ssh_host}", cmd])
    ssh_cmd = prefix_sshpass(ssh_cmd, enabled=use_sshpass)
    try:
        subprocess.run(ssh_cmd, check=True, env=env)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to execute Proxmox Helper Script: %s", e)
        return False


def main(argv: list[str] | argparse.Namespace | None = None) -> int:
    """
    Deploy a homelab node using either Proxmox Helper Scripts, Ansible, or both.
    
    Deployment flow is determined by two Nodes sheet columns:
    - Script URL: If set, run the Proxmox Helper Script
    - Managed: If true, run Ansible (bootstrap + hardening + extra playbooks from Playbooks column)
    
    Examples:
    - Script URL only -> helper script only
    - Managed=true only -> bootstrap + hardening + extra playbooks
    - Both set -> helper script first, then ansible
    - Neither set -> no-op (skip deployment)
    """
    if argv is None:
        argv = sys.argv[1:]

    if isinstance(argv, argparse.Namespace):
        args = argv
    else:
        parser = _build_parser()
        args = parser.parse_args(argv)

    # Config loading - need this before we can load nodes for menu
    config_path: Path = args.config.expanduser().resolve()
    config_dict = load_toml_or_exit(config_path)
    settings = get_effective_table(config_dict, "deploy", inherit=("globals",))
    # Thread CLI options into settings so the lower-level helper can remain simple.
    settings = dict(settings)
    settings["apply"] = bool(getattr(args, "apply", False))

    render_dir: Path | None = getattr(args, "render_dir", None)
    if render_dir is not None:
        settings["render_dir"] = resolve_path_relative_to_config(config_path, render_dir)

    sheet_url = settings.get("sheet_url")
    nodes_gid = settings.get("nodes_gid")
    if not sheet_url or not nodes_gid:
        logger.error("Missing sheet_url or nodes_gid in config")
        return 1

    try:
        nodes_df = get_sheet_df(sheet_url, int(nodes_gid), 30.0, "Nodes")
    except Exception as exc:
        logger.error("Error loading Nodes sheet CSV: %s", exc)
        return 1

    nodes_lookup = load_nodes_lookup(nodes_df)
    
    # If hostname not provided, show interactive menu
    if args.hostname is None:
        selected = _select_deployable_node(nodes_df)
        if selected is None:
            logger.info("No node selected. Exiting.")
            return 0
        args.hostname = selected
        logger.info("Selected node: %s", args.hostname)
    
    # Configure logging level based on --debug flag
    if getattr(args, "debug", False):
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    logger.info("Starting deployment for node: %s", args.hostname)

    # Build Tailscale-aware resolver and stash it inside nodes_lookup so that
    # _resolve_node_shortname_to_ip (which is threaded deeply through the
    # call chain) can use it transparently.
    resolver = build_resolver(config_dict, nodes_df)
    nodes_lookup["_resolver"] = resolver  # type: ignore[assignment]
        
    try:
        node_cfg = get_node_config(nodes_df, args.hostname)
        logger.debug("node_cfg keys: %s", list(node_cfg.keys()))
        logger.debug("node_cfg['script_url']: %s", node_cfg.get("script_url"))
    except ValueError as e:
        logger.error(str(e))
        return 1

    # Bridge is a deploy-time choice, not something taken from the Nodes sheet.
    # Ensure templates always see an explicit value (default: vmbr0).
    bridge = as_str(getattr(args, "bridge", "vmbr0")) or "vmbr0"
    if isinstance(node_cfg.get("node"), dict):
        node_cfg["node"]["bridge"] = bridge

    # Extract deployment fields from Nodes sheet
    row = nodes_df[df_with_normalized_columns(nodes_df)["hostname"].astype(str).str.strip().str.lower() == args.hostname.strip().lower()].iloc[0]
    logger.debug("Node config row for hostname '%s': %s", args.hostname, row.to_dict())
    
    script_url = as_str(node_cfg.get("script_url", "")).strip()
    managed = as_str(row.get("managed", "")).lower() in {"true", "yes", "1"}
    playbooks_value = row.get("playbooks", "")
    
    logger.debug("Deployment config: script_url='%s', managed=%s, playbooks='%s'", 
                 script_url, managed, playbooks_value)
    logger.info("Deployment plan for '%s': run_helper=%s, run_ansible=%s", 
                args.hostname, bool(script_url), managed)

    # Determine what to run
    run_helper = bool(script_url)
    run_ansible = managed
    
    if not run_helper and not run_ansible:
        logger.info("Node '%s' has no Script URL and Managed=false. Skipping deployment.", args.hostname)
        return 0
    
    # Phase 1: Run Proxmox Helper Script if Script URL is set
    if run_helper:
        # Validate that Proxmox Node is set
        proxmox_node = as_str(row.get("proxmox_node", "")).strip()
        if not proxmox_node:
            logger.error("Script URL is set but Proxmox Node is blank for '%s'. Cannot deploy.", args.hostname)
            logger.error("Please set the 'Proxmox Node' column in the Nodes sheet.")
            return 1
        
        logger.info("=" * 60)
        logger.info("PHASE 1: Running Proxmox Helper Script")
        logger.info("Script URL: %s", script_url)
        logger.info("Proxmox Node: %s", proxmox_node)
        logger.info("=" * 60)
        success = run_proxmox_helper_script(
            node_cfg=node_cfg,
            settings=settings,
            config_path=config_path,
            nodes_lookup=nodes_lookup,
        )
        if not success:
            logger.error("Proxmox Helper Script failed for %s", args.hostname)
            return 1
        logger.info("=" * 60)
        logger.info("PHASE 1: Proxmox Helper Script completed successfully")
        logger.info("=" * 60)
    
    # Phase 2: Run Ansible if Managed is true
    if run_ansible:
        logger.info("=" * 60)
        logger.info("PHASE 2: Running Ansible Playbooks")
        logger.info("Node: %s", args.hostname)
        logger.info("=" * 60)
        
        # Parse extra playbooks from Playbooks column
        extra_playbooks = _parse_playbooks_value(playbooks_value)
        
        if extra_playbooks:
            logger.info("Playbooks: bootstrap + hardening + %s", extra_playbooks)
        else:
            logger.info("Playbooks: bootstrap + hardening only")
        
        ansible_success = run_ansible_playbooks(args.hostname, config_path, extra_playbooks)
        if not ansible_success:
            logger.error("Ansible playbooks failed for %s", args.hostname)
            return 1
        logger.info("=" * 60)
        logger.info("PHASE 2: Ansible playbooks completed successfully")
        logger.info("=" * 60)
    
    logger.info("Deployment completed successfully for %s", args.hostname)
    return 0
