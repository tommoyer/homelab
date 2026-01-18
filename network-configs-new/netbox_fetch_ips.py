#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any
import ipaddress

import requests
import tomllib
import tomli_w


def load_config(path: str, debug: bool) -> dict[str, Any]:
    if debug:
        print(f"[debug] Loading config from {path}", file=sys.stderr)
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    if debug:
        print(f"[debug] Loaded config keys: {sorted(data.keys())}", file=sys.stderr)
    return data


def build_url(base_url: str, debug: bool) -> str:
    url = f"{base_url.rstrip('/')}/api/ipam/ip-addresses/"
    if debug:
        print(f"[debug] Built NetBox URL: {url}", file=sys.stderr)
    return url


def fetch_pihole_config(host: str, username: str, debug: bool) -> str:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        f"{username}@{host}",
        "cat /etc/pihole/pihole.toml",
    ]
    if debug:
        print(f"[debug] Fetching pihole.toml via SSH from {username}@{host}", file=sys.stderr)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        if debug:
            print(f"[debug] SSH stderr: {result.stderr.strip()}", file=sys.stderr)
        raise RuntimeError(result.stderr.strip() or "Unknown SSH error")
    if debug:
        print(f"[debug] Fetched {len(result.stdout)} bytes of pihole.toml", file=sys.stderr)
    return result.stdout


def push_pihole_config(host: str, username: str, content: str, debug: bool) -> None:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        f"{username}@{host}",
        "cat > /etc/pihole/pihole.toml",
    ]
    if debug:
        print(f"[debug] Pushing pihole.toml to {username}@{host}", file=sys.stderr)
    result = subprocess.run(
        command, input=content, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Unknown SSH error")
    if debug:
        print(
            f"[debug] Pushed {len(content)} bytes of pihole.toml to {username}@{host}",
            file=sys.stderr,
        )


def reload_pihole_dns(host: str, username: str, debug: bool) -> None:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        f"{username}@{host}",
        "pihole reloaddns",
    ]
    if debug:
        print(f"[debug] Running 'pihole reloaddns' on {username}@{host}", file=sys.stderr)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Unknown SSH error")
    if debug:
        print("[debug] Reloaded Pi-hole DNS config", file=sys.stderr)


def zone_to_filename(zone: str, debug: bool) -> str:
    safe_zone = re.sub(r"[^A-Za-z0-9_.-]+", "_", zone)
    filename = f"pihole-{safe_zone}.toml"
    if debug:
        print(f"[debug] Zone {zone} -> filename {filename}", file=sys.stderr)
    return filename


def zone_to_updated_filename(zone: str, debug: bool) -> str:
    safe_zone = re.sub(r"[^A-Za-z0-9_.-]+", "_", zone)
    filename = f"pihole-{safe_zone}.updated.toml"
    if debug:
        print(f"[debug] Zone {zone} -> updated filename {filename}", file=sys.stderr)
    return filename


def get_netbox_records(payload: Any, debug: bool) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
        if debug:
            print(f"[debug] NetBox payload list -> {len(records)} records", file=sys.stderr)
        return records
    if isinstance(payload, dict):
        results = payload.get("results", [])
        if isinstance(results, list):
            records = [item for item in results if isinstance(item, dict)]
            if debug:
                print(f"[debug] NetBox payload results -> {len(records)} records", file=sys.stderr)
            return records
    if debug:
        print("[debug] NetBox payload not a list or results dict", file=sys.stderr)
    return []


def get_field(record: dict[str, Any], field: str, debug: bool) -> Any:
    if field in record:
        return record[field]
    custom_fields = record.get("custom_fields", {})
    if isinstance(custom_fields, dict):
        field_aliases = {
            "cf_dns_zone": "dns_zone",
            "cf_export_dns": "dns_export",
            "cf_dns_aliases_internal": "dns_aliases_internal",
        }
        lookup_field = field_aliases.get(field, field)
        value = custom_fields.get(lookup_field)
        if debug and value is not None:
            print(
                f"[debug] Field {field} read from custom_fields as {lookup_field}",
                file=sys.stderr,
            )
        return value
    if debug:
        print(f"[debug] Field {field} missing", file=sys.stderr)
    return None


def ensure_dns_section(pihole_data: dict[str, Any], debug: bool) -> dict[str, Any]:
    dns_section = pihole_data.get("dns")
    if not isinstance(dns_section, dict):
        dns_section = {}
        pihole_data["dns"] = dns_section
        if debug:
            print("[debug] Created missing dns section", file=sys.stderr)
    dns_section.setdefault("hosts", [])
    dns_section.setdefault("cnameRecords", [])
    if debug:
        print(
            f"[debug] dns.hosts={len(dns_section['hosts'])}, "
            f"dns.cnameRecords={len(dns_section['cnameRecords'])}",
            file=sys.stderr,
        )
    return dns_section


def parse_aliases(value: Any, debug: bool) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        aliases = [str(item) for item in value if item]
        if debug:
            print(f"[debug] Parsed {len(aliases)} aliases from list", file=sys.stderr)
        return aliases
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            if debug:
                print("[debug] Aliases string not JSON; using raw string", file=sys.stderr)
            return [value]
        if isinstance(parsed, list):
            aliases = [str(item) for item in parsed if item]
            if debug:
                print(f"[debug] Parsed {len(aliases)} aliases from JSON string", file=sys.stderr)
            return aliases
    return []


def is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "y"}
    if isinstance(value, (int, float)):
        return value != 0
    return False


def update_dns_hosts(
    pihole_data: dict[str, Any],
    netbox_records: list[dict[str, Any]],
    zone: str,
    debug: bool,
) -> int:
    if debug:
        print(f"[debug] Updating dns.hosts for zone {zone}", file=sys.stderr)
    dns_section = ensure_dns_section(pihole_data, debug)
    existing = dns_section.get("hosts", [])
    if not isinstance(existing, list):
        existing = []

    new_hosts: list[str] = []
    for record in netbox_records:
        if get_field(record, "cf_dns_zone", debug) != zone:
            continue
        if not is_truthy(get_field(record, "cf_export_dns", debug)):
            continue
        dns_name = get_field(record, "dns_name", debug)
        address = record.get("address")
        if not dns_name or not address:
            if debug:
                print(
                    "[debug] Skipping record missing dns_name or address",
                    file=sys.stderr,
                )
            continue
        ip_address = str(address).split("/", maxsplit=1)[0]
        host_entry = f"{ip_address} {dns_name}"
        new_hosts.append(host_entry)
        if debug:
            print(f"[debug] Prepared host entry: {host_entry}", file=sys.stderr)

    def host_sort_key(entry: str) -> tuple[int, int, str]:
        parts = entry.split()
        if not parts:
            return (2, 0, "")
        ip_text = parts[0]
        hostname = parts[1] if len(parts) > 1 else ""
        try:
            ip_obj = ipaddress.ip_address(ip_text)
            return (0, int(ip_obj), hostname)
        except ValueError:
            return (1, 0, hostname)

    new_hosts.sort(key=host_sort_key)
    dns_section["hosts"] = new_hosts
    added = max(0, len(new_hosts) - len(existing))
    if debug:
        print(
            f"[debug] dns.hosts replaced: {len(existing)} -> {len(new_hosts)}",
            file=sys.stderr,
        )
    return added


def update_dns_cname_records(
    pihole_data: dict[str, Any],
    netbox_records: list[dict[str, Any]],
    zone: str,
    internal_alias_zones: list[str],
    debug: bool,
) -> int:
    if debug:
        print(f"[debug] Updating dns.cnameRecords for zone {zone}", file=sys.stderr)
    dns_section = ensure_dns_section(pihole_data, debug)
    existing = dns_section.get("cnameRecords", [])
    if not isinstance(existing, list):
        existing = []

    new_cname_records: list[str] = []
    alias_zone_set = {zone, *internal_alias_zones}
    for record in netbox_records:
        record_zone = get_field(record, "cf_dns_zone", debug)
        if record_zone not in alias_zone_set:
            continue
        dns_name = get_field(record, "dns_name", debug)
        if not dns_name:
            if debug:
                print("[debug] Skipping record missing dns_name", file=sys.stderr)
            continue
        aliases = parse_aliases(
            get_field(record, "cf_dns_aliases_internal", debug), debug
        )
        if not aliases:
            continue
        for alias in aliases:
            cname_entry = f"{alias},{dns_name}"
            new_cname_records.append(cname_entry)
            if debug:
                print(f"[debug] Prepared CNAME entry: {cname_entry}", file=sys.stderr)

    new_cname_records.sort(key=lambda entry: entry.split(",", 1)[0])
    dns_section["cnameRecords"] = new_cname_records
    added = max(0, len(new_cname_records) - len(existing))
    if debug:
        print(
            f"[debug] dns.cnameRecords replaced: {len(existing)} -> {len(new_cname_records)}",
            file=sys.stderr,
        )
    return added


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch NetBox IP addresses and pretty-print JSON output."
    )
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "config.toml"),
        help="Path to TOML config (default: %(default)s)",
    )
    parser.add_argument(
        "--work-dir",
        help="Directory for downloaded/generated files (overrides config)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug output to stderr",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Push updated pihole.toml to each DNS server and reload Pi-hole DNS",
    )
    args = parser.parse_args()

    config = load_config(args.config, args.debug)
    work_dir = args.work_dir or config.get("work_dir")
    if not work_dir:
        work_dir = os.path.dirname(args.config)
    if args.debug:
        print(f"[debug] Using work_dir={work_dir}", file=sys.stderr)
    os.makedirs(work_dir, exist_ok=True)
    base_url = config.get("base_url")
    if not base_url:
        print("Config must include 'base_url'.", file=sys.stderr)
        return 2

    api_key = os.environ.get("NETBOX_API_KEY")
    if not api_key:
        print("NETBOX_API_KEY environment variable is required.", file=sys.stderr)
        return 2

    url = build_url(base_url, args.debug)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    try:
        if args.debug:
            print("[debug] Requesting NetBox IP addresses", file=sys.stderr)
        response = requests.get(url, headers=headers, timeout=30, verify=False)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON response: {exc}", file=sys.stderr)
        return 1

    json_output_path = os.path.join(work_dir, "netbox-ip-addresses.json")
    with open(json_output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    print(f"Saved NetBox IP address JSON to {json_output_path}")
    netbox_records = get_netbox_records(payload, args.debug)

    dns_zones = config.get("dns_zones", [])
    if dns_zones:
        if args.debug:
            print(f"[debug] Processing {len(dns_zones)} DNS zones", file=sys.stderr)
        for entry in dns_zones:
            zone = entry.get("zone")
            host = entry.get("ip_address")
            username = entry.get("username")
            if not zone or not host or not username:
                print(
                    "Each dns_zones entry must include 'zone', 'ip_address', and 'username'.",
                    file=sys.stderr,
                )
                return 2
            try:
                pihole_config = fetch_pihole_config(host, username, args.debug)
            except RuntimeError as exc:
                print(f"Failed to fetch pihole.toml for {zone}: {exc}", file=sys.stderr)
                return 1

            filename = zone_to_filename(zone, args.debug)
            output_path = os.path.join(work_dir, filename)
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write(pihole_config)
            print(f"Saved pihole config for {zone} to {output_path}")

            try:
                pihole_data = tomllib.loads(pihole_config)
            except tomllib.TOMLDecodeError as exc:
                print(
                    f"Failed to parse pihole.toml for {zone}: {exc}", file=sys.stderr
                )
                return 1

            added_hosts = update_dns_hosts(pihole_data, netbox_records, zone, args.debug)
            internal_alias_zones = entry.get("internal_alias_zones", [])
            if not isinstance(internal_alias_zones, list):
                print(
                    "internal_alias_zones must be a list when provided.",
                    file=sys.stderr,
                )
                return 2
            added_cnames = update_dns_cname_records(
                pihole_data,
                netbox_records,
                zone,
                internal_alias_zones,
                args.debug,
            )
            print(
                f"Prepared updates for {zone}: +{added_hosts} hosts, +{added_cnames} CNAMEs"
            )

            updated_filename = zone_to_updated_filename(zone, args.debug)
            updated_path = os.path.join(work_dir, updated_filename)
            with open(updated_path, "wb") as handle:
                tomli_w.dump(pihole_data, handle)
            print(f"Saved updated pihole config for {zone} to {updated_path}")

            if args.apply:
                push_pihole_config(host, username, tomli_w.dumps(pihole_data), args.debug)
                reload_pihole_dns(host, username, args.debug)
                print(f"Applied updated pihole config for {zone} on {host}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
