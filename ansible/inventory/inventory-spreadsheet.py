#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

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


def load_effective_inventory_config(config_path: Path) -> dict[str, Any]:
    config = load_toml_or_exit(config_path)
    effective = get_effective_table(config, "inventory")
    # Stash full config so build_inventory can access [tailscale] etc.
    effective["_full_config"] = config
    return effective


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

    required_cols = [managed_col, hostname_col, ip_col]
    missing = [col for col in required_cols if col not in set(df.columns)]
    if missing:
        raise RuntimeError(
            "nodes sheet is missing required columns: " + ", ".join(sorted(missing))
        )

    hosts: list[str] = []
    hostvars: dict[str, dict[str, Any]] = {}
    groups: dict[str, set[str]] = {}

    for _, row in df.iterrows():
        row_dict = row.to_dict()

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
        hostvars[hostname] = {"ansible_host": resolver.resolve(hostname) or ip_address}

        host_groups: set[str] = set()
        if roles_col in set(df.columns):
            roles_raw = as_str(row_dict.get(roles_col))
            if roles_raw:
                for role in (part.strip() for part in roles_raw.split(";")):
                    if not role:
                        continue
                    group = normalize_group_name(role)
                    if not group:
                        continue
                    host_groups.add(group)
                    groups.setdefault(group, set()).add(hostname)

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

            # Optional identifiers to avoid ambiguous API lookups
            if proxmox_guest_name_col in set(df.columns):
                proxmox_guest_name = as_str(row_dict.get(proxmox_guest_name_col))
                if proxmox_guest_name:
                    hostvars[hostname]["proxmox_guest_name"] = proxmox_guest_name

            # Column normalization converts "Proxmox Node" -> proxmox_node
            if proxmox_node_col in set(df.columns):
                proxmox_node = as_str(row_dict.get(proxmox_node_col))
                if proxmox_node:
                    hostvars[hostname]["proxmox_node"] = proxmox_node
            if "proxmox_node" in set(df.columns):
                proxmox_node = as_str(row_dict.get("proxmox_node"))
                if proxmox_node:
                    hostvars[hostname]["proxmox_node"] = proxmox_node

            if proxmox_vmid_col in set(df.columns):
                proxmox_vmid = as_str(row_dict.get(proxmox_vmid_col))
                if proxmox_vmid:
                    hostvars[hostname]["proxmox_vmid"] = proxmox_vmid
            if "vmid" in set(df.columns):
                proxmox_vmid = as_str(row_dict.get("vmid"))
                if proxmox_vmid:
                    hostvars[hostname]["proxmox_vmid"] = proxmox_vmid

            if proxmox_type_col in set(df.columns):
                proxmox_type = as_str(row_dict.get(proxmox_type_col)).lower()
                if proxmox_type:
                    hostvars[hostname]["proxmox_type"] = proxmox_type
            if "proxmox_type" in set(df.columns):
                proxmox_type = as_str(row_dict.get("proxmox_type")).lower()
                if proxmox_type:
                    hostvars[hostname]["proxmox_type"] = proxmox_type

    # Stable output
    unique_hosts = sorted(set(hosts))
    group_names = sorted(groups.keys())

    inventory: dict[str, Any] = {
        "_meta": {"hostvars": hostvars},
        "all": {"hosts": unique_hosts, "children": group_names},
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
