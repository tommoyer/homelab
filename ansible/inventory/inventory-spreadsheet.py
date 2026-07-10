#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from homelab.config import get_effective_table, load_toml_or_exit  # noqa: E402
from homelab.resolver import build_resolver  # noqa: E402


def normalize_column_name(name: str) -> str:
    name = (name or "").strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


def df_with_normalized_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [normalize_column_name(str(col)) for col in df.columns]
    return df


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def as_str(value: Any) -> str:
    if is_blank(value):
        return ""
    return str(value).strip()


def normalize_vmid(value: Any) -> str:
    if is_blank(value):
        return ""
    if isinstance(value, (int, float)):
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return ""
    text = as_str(value)
    if not text:
        return ""
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def parse_bool(value: Any, default: bool = False) -> bool:
    if is_blank(value):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            return bool(int(value))
        except (TypeError, ValueError):
            return default
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in {"true", "t", "yes", "y", "1", "on"}:
            return True
        if cleaned in {"false", "f", "no", "n", "0", "off"}:
            return False
    return default


def normalize_nameserver(value: Any) -> str:
    """Normalize nameserver values to the format Proxmox expects.

    Accepts a single IP, or multiple separated by whitespace/commas/semicolons.
    Returns a space-separated string (e.g. "192.168.10.11 1.1.1.1").
    """

    raw = as_str(value)
    if not raw:
        return ""
    parts = [p for p in re.split(r"[\s,;/]+", raw) if p]
    return " ".join(parts)


def build_sheet_url(sheet_url: str, gid: int) -> str:
    if "gid=0" not in sheet_url:
        raise ValueError("sheet_url must contain 'gid=0' placeholder")
    return sheet_url.replace("gid=0", f"gid={gid}")


def normalize_group_name(value: str) -> str:
    cleaned = (value or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    return cleaned


def pluralize_group_name(group: str) -> str:
    """Return a simple plural form for an Ansible inventory group name."""

    if not group:
        return ""
    if group.endswith(("x", "z", "ch", "sh")):
        return f"{group}es"
    if re.search(r"[^aeiou]y$", group):
        return f"{group[:-1]}ies"
    return f"{group}s"


def load_effective_inventory_config(config_path: Path) -> dict[str, Any]:
    config = load_toml_or_exit(config_path)
    effective = get_effective_table(config, "inventory")
    # Stash full config so build_inventory can access [tailscale] etc.
    effective["_full_config"] = config
    return effective


def _normalize_proxmox_api_base(raw_host: str) -> str:
    host = as_str(raw_host)
    if not host:
        return ""
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    host = host.rstrip("/")
    if host.endswith("/api2/json"):
        return host
    return f"{host}/api2/json"


def _resolve_proxmox_api_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    full_cfg = cfg.get("_full_config", {}) or {}
    inventory_cfg = full_cfg.get("inventory", {}) or {}
    deploy_cfg = full_cfg.get("deploy", {}) or {}

    api_host = (
        as_str(os.getenv("PROXMOX_VE_ENDPOINT"))
        or as_str(os.getenv("PROXMOX_ENDPOINT"))
        or as_str(os.getenv("PROXMOX_API_HOST"))
        or as_str(os.getenv("PROXMOX_HOST"))
        or as_str(inventory_cfg.get("proxmox_api_host"))
        or as_str(deploy_cfg.get("proxmox_host"))
    )
    api_user = (
        as_str(os.getenv("PROXMOX_API_USER"))
        or as_str(os.getenv("PROXMOX_USER"))
        or as_str(inventory_cfg.get("proxmox_api_user"))
        or as_str(deploy_cfg.get("proxmox_user"))
    )
    token_id = (
        as_str(os.getenv("PROXMOX_API_TOKEN_ID"))
        or as_str(os.getenv("PROXMOX_TOKEN_ID"))
        or as_str(inventory_cfg.get("proxmox_api_token_id"))
    )
    token_secret = as_str(os.getenv("PROXMOX_API_TOKEN_SECRET")) or as_str(os.getenv("PROXMOX_TOKEN_SECRET"))

    password = as_str(os.getenv("PROXMOX_API_PASSWORD")) or as_str(os.getenv("PROXMOX_PASSWORD"))
    password_env_name = as_str(deploy_cfg.get("proxmox_password_env"))
    if not password and password_env_name:
        password = as_str(os.getenv(password_env_name))

    verify_certs = True
    if "PROXMOX_API_VALIDATE_CERTS" in os.environ:
        verify_certs = parse_bool(os.getenv("PROXMOX_API_VALIDATE_CERTS"), default=True)
    elif "PROXMOX_VERIFY_SSL" in os.environ:
        verify_certs = parse_bool(os.getenv("PROXMOX_VERIFY_SSL"), default=True)
    elif "proxmox_api_validate_certs" in inventory_cfg:
        verify_certs = parse_bool(inventory_cfg.get("proxmox_api_validate_certs"), default=True)

    auth_header = ""
    if token_id and token_secret:
        full_token_id = token_id if "!" in token_id else f"{api_user}!{token_id}"
        auth_header = f"PVEAPIToken={full_token_id}={token_secret}"

    return {
        "api_base": _normalize_proxmox_api_base(api_host),
        "api_user": api_user,
        "password": password,
        "auth_header": auth_header,
        "verify_certs": verify_certs,
    }


def _proxmox_api_get(session: requests.Session, api_base: str, path: str, *, verify_certs: bool) -> dict[str, Any]:
    url = f"{api_base}{path}"
    response = session.get(url, timeout=10, verify=verify_certs)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected Proxmox response payload type for {path}")
    return data


def _login_proxmox_ticket(
    session: requests.Session,
    *,
    api_base: str,
    api_user: str,
    password: str,
    verify_certs: bool,
) -> None:
    if not api_user or not password:
        raise RuntimeError("Proxmox username/password required for ticket auth")

    login_url = f"{api_base}/access/ticket"
    response = session.post(
        login_url,
        data={"username": api_user, "password": password},
        timeout=10,
        verify=verify_certs,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    ticket = as_str(data.get("ticket"))
    csrf = as_str(data.get("CSRFPreventionToken"))
    if not ticket:
        raise RuntimeError("Proxmox login succeeded without a ticket")
    session.cookies.set("PVEAuthCookie", ticket)
    if csrf:
        session.headers["CSRFPreventionToken"] = csrf


def discover_proxmox_guest_inventory(cfg: dict[str, Any]) -> dict[str, dict[str, str]]:
    settings = _resolve_proxmox_api_settings(cfg)
    api_base = as_str(settings.get("api_base"))
    verify_certs = bool(settings.get("verify_certs", True))

    if not api_base:
        print(
            (
                "Warning: Proxmox API discovery skipped "
                "(missing PROXMOX_API_HOST/PROXMOX_HOST or config deploy.proxmox_host)."
            ),
            file=sys.stderr,
        )
        return {}

    session = requests.Session()
    auth_header = as_str(settings.get("auth_header"))

    if auth_header:
        session.headers["Authorization"] = auth_header
    else:
        api_user = as_str(settings.get("api_user"))
        password = as_str(settings.get("password"))
        if not api_user or not password:
            print(
                (
                    "Warning: Proxmox API discovery skipped "
                    "(set token envs PROXMOX_API_TOKEN_ID + PROXMOX_API_TOKEN_SECRET, "
                    "or user/password envs PROXMOX_API_USER + PROXMOX_API_PASSWORD)."
                ),
                file=sys.stderr,
            )
            return {}
        try:
            _login_proxmox_ticket(
                session,
                api_base=api_base,
                api_user=api_user,
                password=password,
                verify_certs=verify_certs,
            )
        except Exception as exc:
            print(f"Warning: Proxmox API discovery login failed: {exc}", file=sys.stderr)
            return {}

    try:
        nodes_payload = _proxmox_api_get(session, api_base, "/nodes", verify_certs=verify_certs)
    except Exception as exc:
        print(f"Warning: Proxmox API discovery failed to list nodes: {exc}", file=sys.stderr)
        return {}

    node_rows = nodes_payload.get("data", []) if isinstance(nodes_payload, dict) else []
    node_names = [as_str(row.get("node")) for row in node_rows if isinstance(row, dict)]
    node_names = [node for node in node_names if node]

    guests_by_name: dict[str, dict[str, str]] = {}
    for node in node_names:
        node_q = quote(node, safe="")
        for vm_type in ("lxc", "qemu"):
            path = f"/nodes/{node_q}/{vm_type}"
            try:
                guest_payload = _proxmox_api_get(session, api_base, path, verify_certs=verify_certs)
            except Exception as exc:
                print(f"Warning: Proxmox API discovery failed for {path}: {exc}", file=sys.stderr)
                continue

            guest_rows = guest_payload.get("data", []) if isinstance(guest_payload, dict) else []
            for row in guest_rows:
                if not isinstance(row, dict):
                    continue
                name = as_str(row.get("name")) or as_str(row.get("hostname"))
                vmid = normalize_vmid(row.get("vmid"))
                if not name or not vmid:
                    continue

                key = name.lower()
                guest_meta = {
                    "name": name,
                    "node": node,
                    "vmid": vmid,
                    "type": vm_type,
                }
                if key in guests_by_name and guests_by_name[key] != guest_meta:
                    # Keep the first match to preserve stable behavior.
                    print(
                        (
                            f"Warning: duplicate Proxmox guest name '{name}' seen on "
                            "multiple nodes; keeping first match "
                            f"{guests_by_name[key]['node']}:{guests_by_name[key]['vmid']}"
                        ),
                        file=sys.stderr,
                    )
                    continue
                guests_by_name[key] = guest_meta

    return guests_by_name


def build_inventory(cfg: dict[str, Any], *, use_tailscale: bool = True) -> dict[str, Any]:
    sheet_url = cfg.get("sheet_url")
    nodes_gid = cfg.get("nodes_gid")
    if not sheet_url:
        raise RuntimeError("missing config value: globals.sheet_url")
    if nodes_gid in (None, ""):
        raise RuntimeError("missing config value: globals.nodes_gid")

    nodes_url = build_sheet_url(str(sheet_url), int(nodes_gid))

    df = pd.read_csv(nodes_url)
    df = df_with_normalized_columns(df)

    # Build the Tailscale-aware resolver.  When a host is on the Tailnet its
    # ansible_host will be set to the Tailscale FQDN; otherwise it falls back
    # to the IP from the spreadsheet.
    full_config = cfg.get("_full_config", {})
    resolver = build_resolver(full_config, df, use_tailscale=use_tailscale)

    managed_col = normalize_column_name(str(cfg.get("managed_col", "Managed")))
    roles_col = normalize_column_name(str(cfg.get("roles_col", "Roles")))
    hostname_col = normalize_column_name(str(cfg.get("hostname_col", "Hostname")))
    ip_col = normalize_column_name(str(cfg.get("ip_col", "IP Address")))

    dns_server_col = normalize_column_name(str(cfg.get("dns_server_col", "DNS Server")))
    searchdomain_col = normalize_column_name(str(cfg.get("searchdomain_col", "Searchdomain")))
    search_domain_col = normalize_column_name(str(cfg.get("search_domain_col", "Search Domain")))
    domain_col = normalize_column_name(str(cfg.get("domain_col", "Domain")))

    proxmox_guest_name_col = normalize_column_name(str(cfg.get("proxmox_guest_name_col", "Proxmox Guest Name")))
    proxmox_node_col = normalize_column_name(str(cfg.get("proxmox_node_col", "Proxmox Node")))
    proxmox_vmid_col = normalize_column_name(str(cfg.get("proxmox_vmid_col", "VMID")))
    proxmox_type_col = normalize_column_name(str(cfg.get("proxmox_type_col", "Proxmox Type")))

    accept_ts_routes_col = normalize_column_name(str(cfg.get("accept_ts_routes_col", "Accept TS Routes")))
    oxidized_model_col = normalize_column_name(str(cfg.get("oxidized_model_col", "Oxidized Model")))

    required_cols = [managed_col, hostname_col, ip_col]
    missing = [col for col in required_cols if col not in set(df.columns)]
    if missing:
        raise RuntimeError(
            "nodes sheet is missing required columns: " + ", ".join(sorted(missing))
        )

    hosts: list[str] = []
    hostvars: dict[str, dict[str, Any]] = {}
    groups: dict[str, set[str]] = {}
    oxidized_device_rows: list[dict[str, str]] = []
    proxmox_guest_node_map: dict[str, str] = {}
    proxmox_guest_vmid_map: dict[str, str] = {}
    proxmox_guest_type_map: dict[str, str] = {}

    for _, row in df.iterrows():
        row_dict = row.to_dict()

        hostname = as_str(row_dict.get(hostname_col))

        # Collect oxidized backup devices regardless of managed flag —
        # network devices are not Ansible-managed but still need to be backed up
        if oxidized_model_col in set(df.columns) and hostname:
            model = as_str(row_dict.get(oxidized_model_col))
            ip = as_str(row_dict.get(ip_col))
            if model and ip:
                oxidized_device_rows.append({"name": hostname, "ip": ip, "model": model})

        if not parse_bool(row_dict.get(managed_col), default=False):
            continue

        hostname = as_str(row_dict.get(hostname_col))
        ip_address = as_str(row_dict.get(ip_col))
        if not hostname or not ip_address:
            continue

        if hostname in hostvars:
            print(
                f"Warning: duplicate hostname in sheet: {hostname}",
                file=sys.stderr,
            )

        hosts.append(hostname)
        hostvars[hostname] = {"ansible_host": resolver.resolve(hostname) or ip_address, "host_ip": ip_address}

        host_groups: set[str] = set()
        if roles_col in set(df.columns):
            roles_raw = as_str(row_dict.get(roles_col))
            if roles_raw:
                for role in (part.strip() for part in roles_raw.split(";")):
                    if not role:
                        continue
                    group = pluralize_group_name(normalize_group_name(role))
                    if not group:
                        continue
                    host_groups.add(group)
                    groups.setdefault(group, set()).add(hostname)

        # Hosts that do not accept Tailscale routes
        if accept_ts_routes_col in set(df.columns):
            if not parse_bool(row_dict.get(accept_ts_routes_col), default=True):
                groups.setdefault("ts_skip_route_accept", set()).add(hostname)

        # Optional Proxmox metadata for all managed guests. This supports
        # tasks that delegate from a guest to its Proxmox node.
        proxmox_guest_name = ""
        if proxmox_guest_name_col in set(df.columns):
            proxmox_guest_name = as_str(row_dict.get(proxmox_guest_name_col))
        if proxmox_guest_name:
            hostvars[hostname]["proxmox_guest_name"] = proxmox_guest_name

        # Column normalization converts "Proxmox Node" -> proxmox_node.
        proxmox_node = ""
        if proxmox_node_col in set(df.columns):
            proxmox_node = as_str(row_dict.get(proxmox_node_col))
        if not proxmox_node and "proxmox_node" in set(df.columns):
            proxmox_node = as_str(row_dict.get("proxmox_node"))
        if proxmox_node:
            hostvars[hostname]["proxmox_node"] = proxmox_node
            proxmox_guest_node_map[hostname] = proxmox_node

        proxmox_vmid = ""
        if proxmox_vmid_col in set(df.columns):
            proxmox_vmid = normalize_vmid(row_dict.get(proxmox_vmid_col))
        if not proxmox_vmid and "proxmox_vmid" in set(df.columns):
            proxmox_vmid = normalize_vmid(row_dict.get("proxmox_vmid"))
        if not proxmox_vmid and "vmid" in set(df.columns):
            proxmox_vmid = normalize_vmid(row_dict.get("vmid"))
        if proxmox_vmid:
            hostvars[hostname]["proxmox_vmid"] = proxmox_vmid
            proxmox_guest_vmid_map[hostname] = proxmox_vmid

        proxmox_type = ""
        if proxmox_type_col in set(df.columns):
            proxmox_type = as_str(row_dict.get(proxmox_type_col)).lower()
        if not proxmox_type and "proxmox_type" in set(df.columns):
            proxmox_type = as_str(row_dict.get("proxmox_type")).lower()
        if proxmox_type:
            hostvars[hostname]["proxmox_type"] = proxmox_type
            proxmox_guest_type_map[hostname] = proxmox_type

        # Proxmox DNS hostvars (only for hosts in the proxmox_dns group)
        if "proxmox_dns" in host_groups:
            nameserver = ""
            if dns_server_col in set(df.columns):
                nameserver = normalize_nameserver(row_dict.get(dns_server_col))
            if nameserver:
                hostvars[hostname]["proxmox_nameserver"] = nameserver

            searchdomain = ""
            if searchdomain_col in set(df.columns):
                searchdomain = as_str(row_dict.get(searchdomain_col))
            if not searchdomain and search_domain_col in set(df.columns):
                searchdomain = as_str(row_dict.get(search_domain_col))
            if not searchdomain and domain_col in set(df.columns):
                searchdomain = as_str(row_dict.get(domain_col))
            if searchdomain:
                hostvars[hostname]["proxmox_searchdomain"] = searchdomain

    # Query Proxmox for authoritative guest metadata and use it to fill/refresh
    # host -> {node, vmid, type} mappings.
    discovered_guests = discover_proxmox_guest_inventory(cfg)
    for hostname, vars_for_host in hostvars.items():
        lookup_name = as_str(vars_for_host.get("proxmox_guest_name")) or hostname
        guest_meta = discovered_guests.get(lookup_name.lower())
        if not guest_meta:
            continue

        vars_for_host["proxmox_guest_name"] = guest_meta["name"]
        vars_for_host["proxmox_node"] = guest_meta["node"]
        vars_for_host["proxmox_vmid"] = guest_meta["vmid"]
        vars_for_host["proxmox_type"] = guest_meta["type"]

        proxmox_guest_node_map[hostname] = guest_meta["node"]
        proxmox_guest_vmid_map[hostname] = guest_meta["vmid"]
        proxmox_guest_type_map[hostname] = guest_meta["type"]

    # Assign oxidized_devices list to the host named "oxidized" (or hosts in
    # an "oxidized" group if one exists)
    if oxidized_device_rows:
        oxidized_targets = groups.get("oxidizeds", set()) or groups.get("oxidized", set())
        if not oxidized_targets and "oxidized" in hostvars:
            oxidized_targets = {"oxidized"}
        for oxidized_host in oxidized_targets:
            hostvars.setdefault(oxidized_host, {})["oxidized_devices"] = oxidized_device_rows

    # Stable output
    unique_hosts = sorted(set(hosts))
    group_names = sorted(groups.keys())

    all_group: dict[str, Any] = {"hosts": unique_hosts, "children": group_names}
    if proxmox_guest_node_map or proxmox_guest_vmid_map or proxmox_guest_type_map:
        all_vars: dict[str, Any] = {}
        if proxmox_guest_node_map:
            all_vars["proxmox_guest_node_map"] = dict(sorted(proxmox_guest_node_map.items()))
        if proxmox_guest_vmid_map:
            all_vars["proxmox_guest_vmid_map"] = dict(sorted(proxmox_guest_vmid_map.items()))
        if proxmox_guest_type_map:
            all_vars["proxmox_guest_type_map"] = dict(sorted(proxmox_guest_type_map.items()))
        all_group["vars"] = all_vars

    inventory: dict[str, Any] = {
        "_meta": {"hostvars": hostvars},
        "all": all_group,
    }

    for group in group_names:
        inventory[group] = {"hosts": sorted(groups[group])}

    return inventory


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dynamic Ansible inventory generated from the homelab spreadsheet",
    )
    parser.add_argument(
        "--config",
        default=str(REPO_ROOT / "config.toml"),
        help="Path to config.toml (default: repo root config.toml)",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--list",
        action="store_true",
        help="Output full inventory JSON",
    )
    mode.add_argument(
        "--host",
        metavar="HOSTNAME",
        help="Output JSON vars for one host",
    )

    parser.add_argument(
        "--no-tailscale",
        action="store_true",
        help="Disable Tailscale-first resolution; always use Sheet IPs",
    )

    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    try:
        cfg = load_effective_inventory_config(Path(args.config))
        inventory = build_inventory(cfg, use_tailscale=not args.no_tailscale)

        if args.host:
            hostvars = inventory.get("_meta", {}).get("hostvars", {})
            payload = hostvars.get(args.host, {})
        else:
            payload = inventory

        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except BrokenPipeError:
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
