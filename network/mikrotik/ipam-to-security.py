#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import urllib.parse
from typing import Any

import requests
import tomllib
import urllib3


def load_config(path: str, debug: bool) -> dict[str, Any]:
    if debug:
        print(f"[debug] Loading config from {path}", file=sys.stderr)
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    if debug:
        print(f"[debug] Loaded config keys: {sorted(data.keys())}", file=sys.stderr)
    return data


def build_ipam_url(base_url: str, debug: bool) -> str:
    url = f"{base_url.rstrip('/')}/api/ipam/ip-addresses/"
    if debug:
        print(f"[debug] Built NetBox URL: {url}", file=sys.stderr)
    return url


def build_ipam_services_url(base_url: str, debug: bool) -> str:
    url = f"{base_url.rstrip('/')}/api/ipam/services/"
    if debug:
        print(f"[debug] Built NetBox services URL: {url}", file=sys.stderr)
    return url


def build_devices_url(base_url: str, debug: bool) -> str:
    url = f"{base_url.rstrip('/')}/api/dcim/devices/"
    if debug:
        print(f"[debug] Built NetBox devices URL: {url}", file=sys.stderr)
    return url


def build_security_url(base_url: str, endpoint: str, debug: bool) -> str:
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        url = endpoint
    else:
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    if debug:
        print(f"[debug] Built NetBox Security URL: {url}", file=sys.stderr)
    return url


def dump_prepared_request(prepared: requests.PreparedRequest) -> None:
    print("[http] Request", file=sys.stderr)
    print(f"{prepared.method} {prepared.url} HTTP/1.1", file=sys.stderr)
    for key, value in prepared.headers.items():
        print(f"{key}: {value}", file=sys.stderr)
    if prepared.body:
        print("", file=sys.stderr)
        body = prepared.body
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        print(body, file=sys.stderr)


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    params: dict[str, str] | None,
    payload: dict[str, Any] | None,
    debug: bool,
    show_http_request: bool,
) -> Any:
    if debug:
        print(f"[debug] Requesting {method} {url} params={params}", file=sys.stderr)
    session = requests.Session()
    request = requests.Request(
        method,
        url,
        headers=headers,
        params=params,
        json=payload,
    )
    prepared = session.prepare_request(request)
    if show_http_request:
        dump_prepared_request(prepared)
    response = session.send(prepared, timeout=30, verify=False)
    response.raise_for_status()
    if response.status_code == 204:
        return None
    return response.json()


def fetch_all_records(
    url: str,
    headers: dict[str, str],
    params: dict[str, str],
    debug: bool,
    show_http_request: bool,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    next_url: str | None = url
    next_params: dict[str, str] | None = params
    
    while next_url:
        payload = request_json(
            "GET",
            next_url,
            headers,
            next_params,
            None,
            debug,
            show_http_request,
        )
        
        if isinstance(payload, list):
            records.extend([item for item in payload if isinstance(item, dict)])
            next_url = None
            continue
        
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected response payload type.")
        
        page_results = payload.get("results", [])
        if isinstance(page_results, list):
            records.extend([item for item in page_results if isinstance(item, dict)])
        else:
            raise RuntimeError("NetBox response missing results list.")
        
        next_url = payload.get("next")
        next_params = None
        
        if debug and next_url:
            print(f"[debug] Following pagination: {next_url}", file=sys.stderr)
    
    return records


def fetch_records_with_tags(
    url: str,
    headers: dict[str, str],
    base_params: dict[str, str],
    tags: list[str],
    debug: bool,
    show_http_request: bool,
) -> list[dict[str, Any]]:
    """Fetch records matching multiple tags (AND logic)."""
    params = base_params.copy()
    
    # NetBox API supports multiple tag filters with AND logic
    # Each tag parameter adds an additional filter
    for tag in tags:
        # Use repeated 'tag' parameter for AND logic
        if 'tag' in params:
            # If tag already exists, we need to handle this differently
            # For now, we'll build a comma-separated list (NetBox supports this)
            existing = params['tag']
            params['tag'] = f"{existing},{tag}"
        else:
            params['tag'] = tag
    
    if debug:
        print(f"[debug] Fetching with tags (AND): {tags}", file=sys.stderr)
    
    return fetch_all_records(url, headers, params, debug, show_http_request)


def fetch_records_with_any_tags(
    url: str,
    headers: dict[str, str],
    base_params: dict[str, str],
    tags: list[str],
    debug: bool,
    show_http_request: bool,
) -> list[dict[str, Any]]:
    """Fetch records matching any of the provided tags (OR logic)."""
    if not tags:
        return []
    
    if debug:
        print(f"[debug] Fetching with tags (OR): {tags}", file=sys.stderr)
    
    # Fetch for each tag and deduplicate by ID
    all_records: dict[int, dict[str, Any]] = {}
    
    for tag in tags:
        params = base_params.copy()
        params['tag'] = tag
        
        records = fetch_all_records(url, headers, params, debug, show_http_request)
        
        for record in records:
            record_id = record.get('id')
            if isinstance(record_id, int):
                all_records[record_id] = record
    
    if debug:
        print(f"[debug] Fetched {len(all_records)} unique records across {len(tags)} tags", file=sys.stderr)
    
    return list(all_records.values())


def canonicalize_ipam_backref(value: str) -> str:
    path, sep, query = value.partition("?")
    if path.startswith("/ipam/ip-addresses/"):
        path = path.replace("/ipam/ip-addresses/", "/api/ipam/ip-addresses/", 1)
    if path.startswith("/ipam/services/"):
        path = path.replace("/ipam/services/", "/api/ipam/services/", 1)
    if sep:
        return f"{path}?{query}"
    return path


def normalize_backref(value: str, base_url: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urllib.parse.urlparse(value)
        normalized = urllib.parse.urlunparse(
            ("", "", parsed.path, parsed.params, parsed.query, parsed.fragment)
        )
        return canonicalize_ipam_backref(normalized)
    
    if value.startswith(base_url):
        return canonicalize_ipam_backref(value[len(base_url):])
    
    return canonicalize_ipam_backref(value)


def build_backref(record: dict[str, Any], base_url: str) -> str | None:
    backref = record.get("display_url") or record.get("url")
    if isinstance(backref, str) and backref:
        return normalize_backref(backref, base_url.rstrip("/"))
    return None


def extract_automation_key(record: dict[str, Any], key_field: str) -> str | None:
    """Extract automation_key from custom fields."""
    custom_fields = record.get("custom_fields", {})
    if isinstance(custom_fields, dict):
        value = custom_fields.get(key_field)
        if isinstance(value, str) and value:
            return value
    return None


def build_security_payload(
    record: dict[str, Any],
    backref_field: str,
    automation_key_field: str,
    base_url: str,
    debug: bool,
) -> dict[str, Any] | None:
    address = record.get("address")
    if not isinstance(address, str) or not address:
        if debug:
            print(
                f"[debug] Skipping record with missing address: {record.get('id')}",
                file=sys.stderr,
            )
        return None
    
    address = normalize_security_address(address, debug, record.get("id"))
    dns_name = record.get("dns_name")
    if not isinstance(dns_name, str) or not dns_name:
        dns_name = ""
    
    name = dns_name or address
    backref = build_backref(record, base_url)
    
    if not backref:
        if debug:
            print(
                f"[debug] Skipping record with missing backref: {record.get('id')}",
                file=sys.stderr,
            )
        return None
    
    payload: dict[str, Any] = {
        "name": name,
        "address": address,
        "custom_fields": {backref_field: backref},
    }
    
    if dns_name:
        payload["dns_name"] = dns_name
    
    # Add automation_key if present in source record
    automation_key = extract_automation_key(record, automation_key_field)
    if automation_key:
        payload["custom_fields"][automation_key_field] = automation_key
    
    return payload


def normalize_security_address(address: str, debug: bool, record_id: Any) -> str:
    """
    Normalize IP addresses to host addresses (/32 for IPv4, /128 for IPv6).
    This ensures Security Address objects represent individual hosts.
    """
    try:
        interface = ipaddress.ip_interface(address)
    except ValueError:
        if debug:
            print(
                f"[debug] Invalid address '{address}' for record {record_id}",
                file=sys.stderr,
            )
        return address
    
    # Convert to host address if not already
    if interface.version == 4:
        if interface.network.prefixlen != 32:
            return f"{interface.ip}/32"
    elif interface.version == 6:
        if interface.network.prefixlen != 128:
            return f"{interface.ip}/128"
    
    return str(interface)


def extract_backref_value(
    record: dict[str, Any], backref_field: str, base_url: str
) -> str | None:
    custom_fields = record.get("custom_fields", {})
    if isinstance(custom_fields, dict):
        value = custom_fields.get(backref_field)
        if isinstance(value, str) and value:
            return normalize_backref(value, base_url.rstrip("/"))
    return None


def parse_service_address_sets(
    config_section: dict[str, Any], debug: bool
) -> list[dict[str, Any]]:
    raw_sets = config_section.get("address_sets")
    if raw_sets is None:
        raw_sets = config_section.get("service_address_sets", [])
    if raw_sets is None:
        return []
    
    if not isinstance(raw_sets, list):
        raise ValueError("ipam_to_security.address_sets must be a list")
    
    mappings: list[dict[str, Any]] = []
    for entry in raw_sets:
        if not isinstance(entry, dict):
            raise ValueError("address_sets entries must be tables")
        
        # Support legacy 'tag' field or new 'intent_tags_any'
        intent_tags = entry.get("intent_tags_any") or entry.get("intent_tags")
        if intent_tags is None:
            # Fall back to legacy single tag
            legacy_tag = entry.get("tag") or entry.get("tag_slug")
            if legacy_tag:
                intent_tags = [legacy_tag]
            else:
                intent_tags = []
        
        if isinstance(intent_tags, str):
            intent_tags = [intent_tags]
        
        if not isinstance(intent_tags, list):
            raise ValueError("intent_tags_any must be a list or string")
        
        name = entry.get("address_set") or entry.get("name")
        sources = entry.get("sources") or entry.get("source")
        automation_key = entry.get("automation_key")
        description = entry.get("description", "")
        
        if not intent_tags or not name:
            raise ValueError("address_sets entries require intent_tags_any and address_set/name")
        
        if sources is None:
            sources = ["services", "devices"]
        
        if isinstance(sources, str):
            sources = [sources]
        
        if not isinstance(sources, list):
            raise ValueError("address_sets sources must be a list")
        
        normalized_sources = [str(item).strip().lower() for item in sources if item]
        normalized_tags = [str(tag).strip() for tag in intent_tags if tag]
        
        mapping = {
            "intent_tags": normalized_tags,
            "name": str(name),
            "sources": normalized_sources,
            "description": str(description) if description else "",
        }
        
        if automation_key:
            mapping["automation_key"] = str(automation_key)
        
        mappings.append(mapping)
    
    if debug:
        print(
            f"[debug] Loaded {len(mappings)} service address set mappings",
            file=sys.stderr,
        )
    
    return mappings


def build_tag_backref(tags: list[str]) -> str:
    """Build backref for address set based on intent tags."""
    # Use first tag for backref (legacy compatibility)
    if tags:
        return f"/api/extras/tags/?slug={urllib.parse.quote(tags[0])}"
    return ""


def build_address_set_payload(
    name: str,
    address_ids: list[int],
    backref_field: str,
    automation_key_field: str,
    backref_value: str,
    automation_key: str | None,
    description: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "addresses": sorted(set(address_ids)),
    }
    
    if description:
        payload["description"] = description
    
    custom_fields = {}
    if backref_value:
        custom_fields[backref_field] = backref_value
    
    if automation_key:
        custom_fields[automation_key_field] = automation_key
    
    if custom_fields:
        payload["custom_fields"] = custom_fields
    
    return payload


def extract_service_ipaddresses(
    service: dict[str, Any], debug: bool
) -> list[dict[str, Any]]:
    ipaddresses = service.get("ipaddresses", [])
    if not isinstance(ipaddresses, list):
        if debug:
            print(
                f"[debug] Service {service.get('id')} ipaddresses not a list",
                file=sys.stderr,
            )
        return []
    
    if debug:
        print(
            f"[debug] Service {service.get('id')} has {len(ipaddresses)} ipaddresses",
            file=sys.stderr,
        )
    
    return [item for item in ipaddresses if isinstance(item, dict)]


def extract_device_ipaddresses(
    device: dict[str, Any], debug: bool
) -> list[dict[str, Any]]:
    ip_records: list[dict[str, Any]] = []
    
    for key in ("primary_ip4", "primary_ip6", "primary_ip"):
        value = device.get(key)
        if isinstance(value, dict):
            ip_records.append(value)
    
    if debug:
        print(
            f"[debug] Device {device.get('id')} resolved {len(ip_records)} primary IPs",
            file=sys.stderr,
        )
    
    return ip_records


def get_security_address_id(
    record: dict[str, Any],
    existing_by_backref: dict[str, dict[str, Any]],
    existing_by_automation_key: dict[str, dict[str, Any]],
    backref_field: str,
    automation_key_field: str,
    base_url: str,
    security_url: str,
    headers: dict[str, str],
    apply_changes: bool,
    show_payload: bool,
    debug: bool,
    show_http_request: bool,
) -> int | None:
    payload = build_security_payload(
        record, backref_field, automation_key_field, base_url, debug
    )
    if payload is None:
        return None
    
    backref_value = None
    automation_key = None
    custom_fields = payload.get("custom_fields")
    if isinstance(custom_fields, dict):
        value = custom_fields.get(backref_field)
        if isinstance(value, str) and value:
            backref_value = value
        
        key_value = custom_fields.get(automation_key_field)
        if isinstance(key_value, str) and key_value:
            automation_key = key_value
    
    # Try to find existing record by backref first (primary match)
    existing = None
    if backref_value:
        existing = existing_by_backref.get(backref_value)
        if existing:
            if debug:
                print(
                    f"[debug] Matched by backref: {backref_value}",
                    file=sys.stderr,
                )
    
    # Fall back to automation_key if no backref match
    if not existing and automation_key:
        existing = existing_by_automation_key.get(automation_key)
        if existing:
            if debug:
                print(
                    f"[debug] Matched by automation_key: {automation_key}",
                    file=sys.stderr,
                )
    
    if existing:
        record_id = existing.get("id")
        if isinstance(record_id, int):
            return record_id
        if debug:
            print(
                f"[debug] Existing Security address missing id",
                file=sys.stderr,
            )
        return None
    
    if not apply_changes:
        if debug:
            print(
                "[debug] Not creating Security address (apply disabled)",
                file=sys.stderr,
            )
        return None
    
    if debug:
        print(
            f"[debug] Creating Security address for {payload.get('address')}",
            file=sys.stderr,
        )
    
    if show_payload:
        print(f"PAYLOAD\tCREATE\t{json.dumps(payload, sort_keys=True)}")
    
    created = request_json(
        "POST",
        security_url,
        headers,
        None,
        payload,
        debug,
        show_http_request,
    )
    
    if isinstance(created, dict):
        if backref_value:
            existing_by_backref[backref_value] = created
        if automation_key:
            existing_by_automation_key[automation_key] = created
        
        record_id = created.get("id")
        if isinstance(record_id, int):
            return record_id
    
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync NetBox IPAM objects to Security module with managed tags and automation keys."
    )
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "config.toml"),
        help="Path to TOML config (default: %(default)s)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Page size for NetBox pagination (default: %(default)s)",
    )
    parser.add_argument(
        "--security-endpoint",
        default=None,
        help=(
            "Security addresses API endpoint (default: config or "
            "/api/plugins/netbox-security/addresses/)"
        ),
    )
    parser.add_argument(
        "--backref-field",
        default="ipam_backref",
        help="Custom field name used to store IPAM backref (default: %(default)s)",
    )
    parser.add_argument(
        "--automation-key-field",
        default="automation_key",
        help="Custom field name for stable automation identity (default: %(default)s)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create/update NetBox Security addresses and address sets",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update existing Security addresses when backref/automation_key matches",
    )
    parser.add_argument(
        "--show-payload",
        action="store_true",
        help="Print JSON payloads sent to the create/update API",
    )
    parser.add_argument(
        "--show-http-request",
        action="store_true",
        help="Print full HTTP requests sent to NetBox",
    )
    parser.add_argument(
        "--suppress-insecure-warning",
        action="store_true",
        help="Suppress InsecureRequestWarning when verify=False",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug output to stderr",
    )
    
    args = parser.parse_args()
    
    config = load_config(args.config, args.debug)
    ipam_to_security_config = config.get("ipam_to_security", {})
    if ipam_to_security_config is None:
        ipam_to_security_config = {}
    
    if not isinstance(ipam_to_security_config, dict):
        print("Config ipam_to_security must be a table.", file=sys.stderr)
        return 2
    
    # Load config defaults
    default_limit = parser.get_default("limit")
    default_backref_field = parser.get_default("backref_field")
    default_automation_key_field = parser.get_default("automation_key_field")
    
    config_limit = ipam_to_security_config.get("limit")
    if isinstance(config_limit, int) and args.limit == default_limit:
        args.limit = config_limit
    
    config_backref_field = ipam_to_security_config.get("backref_field")
    if isinstance(config_backref_field, str) and args.backref_field == default_backref_field:
        args.backref_field = config_backref_field
    
    config_automation_key_field = ipam_to_security_config.get("automation_key_field")
    if isinstance(config_automation_key_field, str) and args.automation_key_field == default_automation_key_field:
        args.automation_key_field = config_automation_key_field
    
    # Load managed_tags_all
    managed_tags_all = ipam_to_security_config.get("managed_tags_all", [])
    if isinstance(managed_tags_all, str):
        managed_tags_all = [managed_tags_all]
    if not isinstance(managed_tags_all, list):
        print("Config managed_tags_all must be a list.", file=sys.stderr)
        return 2
    
    managed_tags_all = [str(tag).strip() for tag in managed_tags_all if tag]
    
    if not managed_tags_all:
        print(
            "WARNING: No managed_tags_all configured. Script will process ALL objects.",
            file=sys.stderr,
        )
    
    # Load boolean flags from config
    for flag_name in (
        "apply",
        "update",
        "show_payload",
        "show_http_request",
        "suppress_insecure_warning",
        "debug",
    ):
        if not getattr(args, flag_name):
            value = ipam_to_security_config.get(flag_name)
            if isinstance(value, bool) and value:
                setattr(args, flag_name, True)
    
    if args.suppress_insecure_warning:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    base_url = config.get("base_url")
    if not base_url:
        print("Config must include 'base_url'.", file=sys.stderr)
        return 2
    
    api_key = os.environ.get("NETBOX_API_KEY")
    if not api_key:
        print("NETBOX_API_KEY environment variable is required.", file=sys.stderr)
        return 2
    
    ipam_url = build_ipam_url(base_url, args.debug)
    
    security_endpoint = (
        args.security_endpoint
        or ipam_to_security_config.get("security_endpoint")
        or config.get("netbox_security_addresses_endpoint")
        or "/api/plugins/netbox-security/addresses/"
    )
    security_url = build_security_url(base_url, security_endpoint, args.debug)
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    
    base_params: dict[str, str] = {
        "limit": str(args.limit),
    }
    
    # Fetch IPAM records with managed_tags_all filter
    try:
        if managed_tags_all:
            ipam_records = fetch_records_with_tags(
                ipam_url, headers, base_params, managed_tags_all, args.debug, args.show_http_request
            )
        else:
            ipam_records = fetch_all_records(
                ipam_url, headers, base_params, args.debug, args.show_http_request
            )
    except requests.RequestException as exc:
        print(f"IPAM request failed: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Unexpected IPAM response: {exc}", file=sys.stderr)
        return 1
    
    # Fetch existing Security addresses
    security_params: dict[str, str] = {
        "limit": str(args.limit),
    }
    
    try:
        security_records = fetch_all_records(
            security_url, headers, security_params, args.debug, args.show_http_request
        )
    except requests.RequestException as exc:
        print(f"Security request failed: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Unexpected security response: {exc}", file=sys.stderr)
        return 1
    
    # Build lookup tables for existing Security addresses
    existing_by_backref: dict[str, dict[str, Any]] = {}
    existing_by_automation_key: dict[str, dict[str, Any]] = {}
    
    for record in security_records:
        backref_value = extract_backref_value(record, args.backref_field, base_url)
        if backref_value:
            existing_by_backref[backref_value] = record
        
        automation_key = extract_automation_key(record, args.automation_key_field)
        if automation_key:
            existing_by_automation_key[automation_key] = record
    
    if args.debug:
        print(
            f"[debug] Loaded {len(existing_by_backref)} Security addresses by backref, "
            f"{len(existing_by_automation_key)} by automation_key",
            file=sys.stderr,
        )
    
    # Process individual IP addresses
    created = 0
    updated = 0
    skipped = 0
    
    for record in ipam_records:
        payload = build_security_payload(
            record, args.backref_field, args.automation_key_field, base_url, args.debug
        )
        if payload is None:
            skipped += 1
            continue
        
        backref_value = None
        automation_key = None
        custom_fields = payload.get("custom_fields")
        if isinstance(custom_fields, dict):
            value = custom_fields.get(args.backref_field)
            if isinstance(value, str) and value:
                backref_value = value
            
            key_value = custom_fields.get(args.automation_key_field)
            if isinstance(key_value, str) and key_value:
                automation_key = key_value
        
        # Check for existing record
        existing = None
        if backref_value:
            existing = existing_by_backref.get(backref_value)
        if not existing and automation_key:
            existing = existing_by_automation_key.get(automation_key)
        
        if existing:
            if not args.update:
                skipped += 1
                print(f"SKIP\t{payload['name']}\t{payload['address']}\t{backref_value or automation_key}")
                continue
            
            target_url = existing.get("url")
            if not isinstance(target_url, str) or not target_url:
                record_id = existing.get("id")
                target_url = f"{security_url.rstrip('/')}/{record_id}/"
            
            if args.apply:
                try:
                    if args.show_payload:
                        print(
                            f"PAYLOAD\tUPDATE\t{json.dumps(payload, sort_keys=True)}"
                        )
                    
                    updated_record = request_json(
                        "PATCH",
                        target_url,
                        headers,
                        None,
                        payload,
                        args.debug,
                        args.show_http_request,
                    )
                    
                    if isinstance(updated_record, dict):
                        if backref_value:
                            existing_by_backref[backref_value] = updated_record
                        if automation_key:
                            existing_by_automation_key[automation_key] = updated_record
                
                except requests.RequestException as exc:
                    print(f"Update failed: {exc}", file=sys.stderr)
                    return 1
            
            updated += 1
            print(f"UPDATE\t{payload['name']}\t{payload['address']}\t{backref_value or automation_key}")
            continue
        
        # Create new record
        if args.apply:
            try:
                if args.show_payload:
                    print(f"PAYLOAD\tCREATE\t{json.dumps(payload, sort_keys=True)}")
                
                created_record = request_json(
                    "POST",
                    security_url,
                    headers,
                    None,
                    payload,
                    args.debug,
                    args.show_http_request,
                )
                
                if isinstance(created_record, dict):
                    if backref_value:
                        existing_by_backref[backref_value] = created_record
                    if automation_key:
                        existing_by_automation_key[automation_key] = created_record
            
            except requests.RequestException as exc:
                print(f"Create failed: {exc}", file=sys.stderr)
                return 1
        
        created += 1
        print(f"CREATE\t{payload['name']}\t{payload['address']}\t{backref_value or automation_key}")
    
    # Process Address Sets
    address_set_created = 0
    address_set_updated = 0
    address_set_skipped = 0
    
    try:
        service_address_sets = parse_service_address_sets(
            ipam_to_security_config, args.debug
        )
    except ValueError as exc:
        print(f"Invalid service_address_sets configuration: {exc}", file=sys.stderr)
        return 2
    
    if service_address_sets:
        services_url = build_ipam_services_url(base_url, args.debug)
        devices_url = build_devices_url(base_url, args.debug)
        
        address_sets_endpoint = (
            ipam_to_security_config.get("address_sets_endpoint")
            or config.get("netbox_security_address_sets_endpoint")
            or "/api/plugins/netbox-security/address-sets/"
        )
        address_sets_url = build_security_url(
            base_url, address_sets_endpoint, args.debug
        )
        
        address_set_backref_field = (
            ipam_to_security_config.get("address_set_backref_field")
            or args.backref_field
        )
        
        # Fetch existing address sets
        try:
            address_sets = fetch_all_records(
                address_sets_url,
                headers,
                security_params,
                args.debug,
                args.show_http_request,
            )
        except requests.RequestException as exc:
            print(f"Address set request failed: {exc}", file=sys.stderr)
            return 1
        except RuntimeError as exc:
            print(f"Unexpected address set response: {exc}", file=sys.stderr)
            return 1
        
        # Build lookup tables for address sets
        existing_sets_by_backref: dict[str, dict[str, Any]] = {}
        existing_sets_by_automation_key: dict[str, dict[str, Any]] = {}
        existing_sets_by_name: dict[str, dict[str, Any]] = {}
        
        for record in address_sets:
            backref_value = extract_backref_value(
                record, address_set_backref_field, base_url
            )
            if backref_value:
                existing_sets_by_backref[backref_value] = record
            
            automation_key = extract_automation_key(record, args.automation_key_field)
            if automation_key:
                existing_sets_by_automation_key[automation_key] = record
            
            name = record.get("name")
            if isinstance(name, str) and name:
                existing_sets_by_name[name] = record
        
        if args.debug:
            print(
                f"[debug] Loaded {len(existing_sets_by_backref)} Address Sets by backref, "
                f"{len(existing_sets_by_automation_key)} by automation_key",
                file=sys.stderr,
            )
        
        # Process each address set mapping
        for mapping in service_address_sets:
            intent_tags = mapping["intent_tags"]
            set_name = mapping["name"]
            sources = mapping.get("sources") or []
            automation_key = mapping.get("automation_key")
            description = mapping.get("description", "")
            
            if args.debug:
                print(
                    f"[debug] Building AddressSet '{set_name}' from tags {intent_tags}",
                    file=sys.stderr,
                )
            
            address_ids: list[int] = []
            missing_ids = 0
            
            # Combine managed_tags_all with intent_tags for filtering
            all_required_tags = managed_tags_all.copy()
            
            for source in sources:
                if source == "services":
                    # Fetch services matching intent tags (OR) AND managed tags (AND)
                    try:
                        if intent_tags:
                            services = fetch_records_with_any_tags(
                                services_url,
                                headers,
                                base_params,
                                intent_tags,
                                args.debug,
                                args.show_http_request,
                            )
                        else:
                            services = []
                        
                        # Filter services to ensure they also have all managed tags
                        if all_required_tags:
                            filtered_services = []
                            for service in services:
                                service_tags = service.get("tags", [])
                                service_tag_slugs = [
                                    tag.get("slug") for tag in service_tags
                                    if isinstance(tag, dict) and tag.get("slug")
                                ]
                                
                                has_all_managed = all(
                                    tag in service_tag_slugs for tag in all_required_tags
                                )
                                if has_all_managed:
                                    filtered_services.append(service)
                            
                            services = filtered_services
                    
                    except requests.RequestException as exc:
                        print(f"Services request failed: {exc}", file=sys.stderr)
                        return 1
                    except RuntimeError as exc:
                        print(f"Unexpected services response: {exc}", file=sys.stderr)
                        return 1
                    
                    for service in services:
                        for ip_record in extract_service_ipaddresses(service, args.debug):
                            address_id = get_security_address_id(
                                ip_record,
                                existing_by_backref,
                                existing_by_automation_key,
                                args.backref_field,
                                args.automation_key_field,
                                base_url,
                                security_url,
                                headers,
                                args.apply,
                                args.show_payload,
                                args.debug,
                                args.show_http_request,
                            )
                            
                            if address_id is not None:
                                address_ids.append(address_id)
                            else:
                                missing_ids += 1
                    
                    continue
                
                if source == "devices":
                    # Fetch devices matching intent tags (OR) AND managed tags (AND)
                    try:
                        if intent_tags:
                            devices = fetch_records_with_any_tags(
                                devices_url,
                                headers,
                                base_params,
                                intent_tags,
                                args.debug,
                                args.show_http_request,
                            )
                        else:
                            devices = []
                        
                        # Filter devices to ensure they also have all managed tags
                        if all_required_tags:
                            filtered_devices = []
                            for device in devices:
                                device_tags = device.get("tags", [])
                                device_tag_slugs = [
                                    tag.get("slug") for tag in device_tags
                                    if isinstance(tag, dict) and tag.get("slug")
                                ]
                                
                                has_all_managed = all(
                                    tag in device_tag_slugs for tag in all_required_tags
                                )
                                if has_all_managed:
                                    filtered_devices.append(device)
                            
                            devices = filtered_devices
                    
                    except requests.RequestException as exc:
                        print(f"Devices request failed: {exc}", file=sys.stderr)
                        return 1
                    except RuntimeError as exc:
                        print(f"Unexpected devices response: {exc}", file=sys.stderr)
                        return 1
                    
                    for device in devices:
                        for ip_record in extract_device_ipaddresses(device, args.debug):
                            address_id = get_security_address_id(
                                ip_record,
                                existing_by_backref,
                                existing_by_automation_key,
                                args.backref_field,
                                args.automation_key_field,
                                base_url,
                                security_url,
                                headers,
                                args.apply,
                                args.show_payload,
                                args.debug,
                                args.show_http_request,
                            )
                            
                            if address_id is not None:
                                address_ids.append(address_id)
                            else:
                                missing_ids += 1
                    
                    continue
                
                print(f"Unknown address set source '{source}'", file=sys.stderr)
                return 2
            
            if missing_ids and args.debug:
                print(
                    f"[debug] {missing_ids} tagged IPs missing Security IDs",
                    file=sys.stderr,
                )
            
            if args.debug:
                print(
                    f"[debug] AddressSet '{set_name}' resolved {len(address_ids)} addresses",
                    file=sys.stderr,
                )
            
            # Build backref from intent tags
            backref_value = build_tag_backref(intent_tags)
            
            # Build payload
            payload = build_address_set_payload(
                set_name,
                address_ids,
                address_set_backref_field,
                args.automation_key_field,
                backref_value,
                automation_key,
                description,
            )
            
            # Find existing address set
            existing_set = None
            if automation_key:
                existing_set = existing_sets_by_automation_key.get(automation_key)
            if not existing_set and backref_value:
                existing_set = existing_sets_by_backref.get(backref_value)
            if not existing_set:
                existing_set = existing_sets_by_name.get(set_name)
            
            if existing_set:
                if not args.update:
                    address_set_skipped += 1
                    print(
                        f"ADDRSET\tSKIP\t{set_name}\t{','.join(intent_tags)}\t{len(address_ids)}"
                    )
                    continue
                
                if args.debug:
                    print(
                        f"[debug] Updating AddressSet '{set_name}' with {len(address_ids)} addresses",
                        file=sys.stderr,
                    )
                
                target_url = existing_set.get("url")
                if not isinstance(target_url, str) or not target_url:
                    record_id = existing_set.get("id")
                    target_url = f"{address_sets_url.rstrip('/')}/{record_id}/"
                
                if args.apply:
                    try:
                        if args.show_payload:
                            print(
                                "PAYLOAD\tADDRESSET\tUPDATE\t"
                                f"{json.dumps(payload, sort_keys=True)}"
                            )
                        
                        updated_record = request_json(
                            "PATCH",
                            target_url,
                            headers,
                            None,
                            payload,
                            args.debug,
                            args.show_http_request,
                        )
                        
                        if isinstance(updated_record, dict):
                            if backref_value:
                                existing_sets_by_backref[backref_value] = updated_record
                            if automation_key:
                                existing_sets_by_automation_key[automation_key] = updated_record
                            existing_sets_by_name[set_name] = updated_record
                    
                    except requests.RequestException as exc:
                        print(f"Address set update failed: {exc}", file=sys.stderr)
                        return 1
                
                address_set_updated += 1
                print(
                    f"ADDRSET\tUPDATE\t{set_name}\t{','.join(intent_tags)}\t{len(address_ids)}"
                )
                continue
            
            # Create new address set
            if args.apply:
                try:
                    if args.show_payload:
                        print(
                            "PAYLOAD\tADDRESSET\tCREATE\t"
                            f"{json.dumps(payload, sort_keys=True)}"
                        )
                    
                    if args.debug:
                        print(
                            f"[debug] Creating AddressSet '{set_name}' with {len(address_ids)} addresses",
                            file=sys.stderr,
                        )
                    
                    created_record = request_json(
                        "POST",
                        address_sets_url,
                        headers,
                        None,
                        payload,
                        args.debug,
                        args.show_http_request,
                    )
                    
                    if isinstance(created_record, dict):
                        if backref_value:
                            existing_sets_by_backref[backref_value] = created_record
                        if automation_key:
                            existing_sets_by_automation_key[automation_key] = created_record
                        existing_sets_by_name[set_name] = created_record
                
                except requests.RequestException as exc:
                    print(f"Address set create failed: {exc}", file=sys.stderr)
                    return 1
            
            address_set_created += 1
            print(
                f"ADDRSET\tCREATE\t{set_name}\t{','.join(intent_tags)}\t{len(address_ids)}"
            )
    
    # Print summary
    print(
        "Address Summary: "
        f"created={created} updated={updated} skipped={skipped}"
    )
    
    if service_address_sets:
        print(
            "AddressSet Summary: "
            f"created={address_set_created} "
            f"updated={address_set_updated} "
            f"skipped={address_set_skipped}"
        )
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
