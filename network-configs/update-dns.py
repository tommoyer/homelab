#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import subprocess
import sys
from typing import Any

import requests
import tomllib


def load_config(path: str, debug: bool) -> dict[str, Any]:
    if debug:
        print(f"[debug] Loading config from {path}", file=sys.stderr)
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    if debug:
        print(f"[debug] Loaded config keys: {sorted(data.keys())}", file=sys.stderr)
    return data


def build_url(base_url: str, endpoint: str, debug: bool) -> str:
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        url = endpoint
    else:
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    if debug:
        print(f"[debug] Built NetBox URL: {url}", file=sys.stderr)
    return url


def fetch_all_records(url: str, headers: dict[str, str], debug: bool) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    next_url: str | None = url
    while next_url:
        if debug:
            print(f"[debug] Requesting NetBox DNS records: {next_url}", file=sys.stderr)
        response = requests.get(next_url, headers=headers, timeout=30, verify=False)
        response.raise_for_status()
        payload = response.json()
        batch = get_netbox_records(payload, debug)
        records.extend(batch)
        if isinstance(payload, dict):
            next_url = payload.get("next")
        else:
            next_url = None
        if debug:
            print(
                f"[debug] Collected {len(batch)} records (total {len(records)})",
                file=sys.stderr,
            )
    return records


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
            "cf_dns_aliases_external": "dns_aliases_external",
            "cf_dns_export_views": "dns_export_views",
            "cf_cloudflare_proxy_enabled": "cloudflare_proxy_enabled",
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


def should_export_dns(record: dict[str, Any], debug: bool, default: bool) -> bool:
    value = get_field(record, "cf_export_dns", debug)
    if value is None:
        if debug:
            print(
                f"[debug] cf_export_dns missing; defaulting to {default}",
                file=sys.stderr,
            )
        return default
    return is_truthy(value)


def extract_proxy_enabled(record: dict[str, Any], debug: bool) -> bool:
    value = get_field(record, "cloudflare_proxy_enabled", debug)
    if value is not None:
        return is_truthy(value)
    value = get_field(record, "cf_cloudflare_proxy_enabled", debug)
    if value is not None:
        return is_truthy(value)
    ip_candidate = record.get("ip_address") or record.get("ipaddress")
    if isinstance(ip_candidate, dict):
        custom_fields = ip_candidate.get("custom_fields", {})
        if isinstance(custom_fields, dict):
            if "cloudflare_proxy_enabled" in custom_fields:
                value = custom_fields.get("cloudflare_proxy_enabled")
                if debug:
                    print(
                        "[debug] cloudflare_proxy_enabled read from ip_address custom_fields",
                        file=sys.stderr,
                    )
                return is_truthy(value)
            if "cf_cloudflare_proxy_enabled" in custom_fields:
                value = custom_fields.get("cf_cloudflare_proxy_enabled")
                if debug:
                    print(
                        "[debug] cf_cloudflare_proxy_enabled read from ip_address custom_fields",
                        file=sys.stderr,
                    )
                return is_truthy(value)
    return False


def normalize_zone(value: str) -> str:
    return value.strip().strip(".").lower()


def dns_name_in_zone(dns_name: str, zone: str) -> bool:
    dns_name = normalize_zone(dns_name)
    zone = normalize_zone(zone)
    return dns_name == zone or dns_name.endswith(f".{zone}")


def extract_zone_name(record: dict[str, Any]) -> str | None:
    zone = record.get("zone")
    if isinstance(zone, dict):
        return zone.get("name") or zone.get("display") or zone.get("fqdn")
    if isinstance(zone, str):
        return zone
    return None


def extract_view_name(record: dict[str, Any]) -> str | None:
    view = record.get("view")
    if isinstance(view, dict):
        return view.get("name") or view.get("display")
    if isinstance(view, str):
        return view
    zone = record.get("zone")
    if isinstance(zone, dict):
        zone_view = zone.get("view")
        if isinstance(zone_view, dict):
            return zone_view.get("name") or zone_view.get("display")
        if isinstance(zone_view, str):
            return zone_view
    return None


def extract_record_fqdn(record: dict[str, Any], zone_name: str | None) -> str | None:
    fqdn = record.get("fqdn") or record.get("dns_name")
    if isinstance(fqdn, str) and fqdn.strip():
        return fqdn.strip().rstrip(".")
    name = record.get("name") or record.get("hostname")
    if isinstance(name, str):
        name = name.strip().rstrip(".")
    if not name:
        return zone_name
    if name in {"@", "*"}:
        return zone_name
    if zone_name:
        if dns_name_in_zone(name, zone_name):
            return name
        return f"{name}.{zone_name}"
    return name


def extract_record_ip(record: dict[str, Any]) -> str | None:
    for key in ("value", "address", "ip_address", "ip"):
        value = record.get(key)
        if value:
            return str(value).split("/", maxsplit=1)[0]
    return None


def collect_dnscontrol_zones(
    netbox_records: list[dict[str, Any]],
    zone_filters: list[dict[str, Any]],
    debug: bool,
) -> list[str]:
    zones: set[str] = set()
    if zone_filters:
        zones = {entry["zone"] for entry in zone_filters}
    else:
        for record in netbox_records:
            record_view = extract_view_name(record)
            if record_view and record_view.strip().lower() != "external":
                continue
            zone_name = extract_zone_name(record)
            if zone_name:
                zones.add(normalize_zone(str(zone_name)))
    zone_list = sorted(zones)
    if debug:
        print(
            f"[debug] dnscontrol zones: {zone_list}",
            file=sys.stderr,
        )
    return zone_list


def parse_zone_filters(config: dict[str, Any], debug: bool) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    raw_filters = config.get("netbox_zone_filters", [])
    if not raw_filters:
        if debug:
            print("[debug] No netbox_zone_filters configured", file=sys.stderr)
        return filters
    if not isinstance(raw_filters, list):
        raise ValueError("netbox_zone_filters must be a list")
    for entry in raw_filters:
        if not isinstance(entry, dict):
            raise ValueError("Each netbox_zone_filters entry must be a table")
        zone = entry.get("zone")
        views = entry.get("views", ["external"])
        if not zone:
            raise ValueError("netbox_zone_filters entries require 'zone'")
        if not isinstance(views, list):
            raise ValueError("netbox_zone_filters.views must be a list")
        filters.append(
            {
                "zone": normalize_zone(str(zone)),
                "views": {str(view).strip().lower() for view in views if view},
            }
        )
    if debug:
        print(
            f"[debug] Loaded {len(filters)} netbox_zone_filters entries",
            file=sys.stderr,
        )
    return filters


def build_cloudflare_records(
    netbox_records: list[dict[str, Any]],
    zone_filters: list[dict[str, Any]],
    debug: bool,
) -> list[dict[str, Any]]:
    if debug:
        print("[debug] Building Cloudflare external records", file=sys.stderr)
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for record in netbox_records:
        if not should_export_dns(record, debug, default=True):
            continue
        record_zone = extract_zone_name(record)
        record_view = extract_view_name(record)
        record_fqdn = extract_record_fqdn(record, record_zone)
        record_type = str(record.get("type") or record.get("record_type") or "").upper()
        if record_type and record_type not in {"A", "AAAA"}:
            continue
        if zone_filters:
            match = False
            for entry in zone_filters:
                zone = entry["zone"]
                entry_views = entry["views"]
                if entry_views:
                    if not record_view or record_view.strip().lower() not in entry_views:
                        continue
                if record_zone and normalize_zone(str(record_zone)) == zone:
                    match = True
                    break
                if record_fqdn and dns_name_in_zone(str(record_fqdn), zone):
                    match = True
                    break
            if not match:
                continue
        else:
            if not record_view or record_view.strip().lower() != "external":
                continue
        if not record_fqdn:
            if debug:
                print("[debug] Skipping record missing fqdn", file=sys.stderr)
            continue
        ip_text = extract_record_ip(record)
        if not ip_text:
            if debug:
                print("[debug] Skipping record missing IP value", file=sys.stderr)
            continue
        try:
            ipaddress.ip_address(ip_text)
        except ValueError:
            if debug:
                print(f"[debug] Skipping invalid IP address: {ip_text}", file=sys.stderr)
            continue
        alias = str(record_fqdn).strip().rstrip(".")
        key = (alias, ip_text)
        if key in seen:
            continue
        seen.add(key)
        proxied = extract_proxy_enabled(record, debug)
        records.append({"name": alias, "target": ip_text, "proxied": proxied})
        if debug:
            print(
                f"[debug] External record: {alias} -> {ip_text} (proxied={proxied})",
                file=sys.stderr,
            )

    records.sort(key=lambda item: (item["name"], item["target"]))
    if debug:
        print(f"[debug] Prepared {len(records)} Cloudflare records", file=sys.stderr)
    return records


def write_cloudflare_records(path: str, records: list[dict[str, Any]], debug: bool) -> None:
    if debug:
        print(f"[debug] Writing Cloudflare records to {path}", file=sys.stderr)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2, sort_keys=True)


def run_dnscontrol(
    dnscontrol_dir: str,
    dnscontrol_bin: str,
    apply: bool,
    debug: bool,
    run_check: bool = True,
) -> None:
    def _run(command: list[str]) -> None:
        if debug:
            print(f"[debug] Running: {' '.join(command)}", file=sys.stderr)
        result = subprocess.run(command, cwd=dnscontrol_dir, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"dnscontrol failed: {' '.join(command)}")

    if run_check:
        _run([dnscontrol_bin, "check"])
    _run([dnscontrol_bin, "preview"])
    if apply:
        _run([dnscontrol_bin, "push"])




def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch NetBox IP addresses for Cloudflare via dnscontrol."
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
        "--dnscontrol-dir",
        help="Directory containing dnscontrol config (enables Cloudflare updates)",
    )
    parser.add_argument(
        "--dnscontrol-bin",
        default=None,
        help="dnscontrol binary (default: dnscontrol)",
    )
    parser.add_argument(
        "--dnscontrol-records-path",
        default=None,
        help="Output path for external_records.json (default: work_dir or dnscontrol-dir)",
    )
    parser.add_argument(
        "--dnscontrol-no-check",
        action="store_true",
        help="Skip dnscontrol check step",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply dnscontrol push after preview",
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

    endpoint = config.get("netbox_dns_endpoint") or "/api/plugins/netbox-dns/records/"
    url = build_url(base_url, endpoint, args.debug)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    try:
        netbox_records = fetch_all_records(url, headers, args.debug)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON response: {exc}", file=sys.stderr)
        return 1

    json_output_path = os.path.join(work_dir, "netbox-dns-records.json")
    payload = {
        "count": len(netbox_records),
        "next": None,
        "previous": None,
        "results": netbox_records,
    }
    with open(json_output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    print(f"Saved NetBox DNS records JSON to {json_output_path}")

    dnscontrol_dir = args.dnscontrol_dir or config.get("dnscontrol_dir")
    dnscontrol_bin = args.dnscontrol_bin or config.get("dnscontrol_bin") or "/usr/bin/dnscontrol"
    dnscontrol_records_path = (
        args.dnscontrol_records_path or config.get("dnscontrol_records_path")
    )

    creds_path = os.path.join(os.path.dirname(__file__), "creds.json")
    dnscontrol_base_dir = None
    if os.path.isfile(creds_path):
        dnscontrol_base_dir = os.path.dirname(creds_path)
    if not dnscontrol_base_dir:
        dnscontrol_base_dir = work_dir

    if not dnscontrol_records_path:
        dnscontrol_records_path = os.path.join(
            dnscontrol_base_dir, "external_records.json"
        )
    if args.apply and not dnscontrol_dir:
        dnscontrol_dir = dnscontrol_base_dir
        if args.debug:
            print(
                f"[debug] --apply set; defaulting dnscontrol_dir to {dnscontrol_dir}",
                file=sys.stderr,
            )
    dnscontrol_no_check = args.dnscontrol_no_check or config.get("dnscontrol_no_check")

    zone_filters: list[dict[str, Any]] = []
    try:
        zone_filters = parse_zone_filters(config, args.debug)
    except ValueError as exc:
        print(f"Invalid netbox_zone_filters configuration: {exc}", file=sys.stderr)
        return 2

    if dnscontrol_records_path:
        records = build_cloudflare_records(netbox_records, zone_filters, args.debug)
        write_cloudflare_records(dnscontrol_records_path, records, args.debug)
        print(f"Saved Cloudflare external records to {dnscontrol_records_path}")
        if dnscontrol_dir:
            try:
                run_dnscontrol(
                    dnscontrol_dir,
                    dnscontrol_bin,
                    args.apply,
                    args.debug,
                    run_check=not dnscontrol_no_check,
                )
                if args.apply:
                    print("Applied Cloudflare dnscontrol updates.")
                else:
                    print("Previewed Cloudflare dnscontrol updates.")
            except RuntimeError as exc:
                print(f"Cloudflare dnscontrol failed: {exc}", file=sys.stderr)
                return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
