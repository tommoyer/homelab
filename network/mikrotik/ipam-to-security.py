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

# NetBox API endpoints (relative to base_url)
IPAM_IP_ADDRESSES_ENDPOINT = "/api/ipam/ip-addresses/"
IPAM_SERVICES_ENDPOINT = "/api/ipam/services/"
EXTRAS_TAGS_ENDPOINT = "/api/extras/tags/"
VMS_ENDPOINT = "/api/virtualization/virtual-machines/"
DEVICES_ENDPOINT = "/api/dcim/devices/"

SECURITY_ADDRESSES_ENDPOINT = "/api/plugins/netbox-security/addresses/"
SECURITY_ADDRESSSETS_ENDPOINT = "/api/plugins/netbox-security/address-sets/"


def load_config(path: str, debug: bool) -> dict[str, Any]:
    if debug:
        print(f"[debug] Loading config from {path}", file=sys.stderr)
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    if debug:
        print(f"[debug] Loaded config keys: {sorted(data.keys())}", file=sys.stderr)
    return data


def build_ipam_url(base_url: str, debug: bool) -> str:
    url = f"{base_url.rstrip('/')}{IPAM_IP_ADDRESSES_ENDPOINT}"
    if debug:
        print(f"[debug] Built NetBox URL: {url}", file=sys.stderr)
    return url


def build_api_url(base_url: str, endpoint: str, debug: bool) -> str:
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    if debug:
        print(f"[debug] Built NetBox URL: {url}", file=sys.stderr)
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
    session: requests.Session | None = None,
) -> Any:
    if debug:
        print(f"[debug] Requesting {method} {url} params={params}", file=sys.stderr)
    owns_session = session is None
    if session is None:
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
    try:
        response = session.send(prepared, timeout=30, verify=False)
    finally:
        if owns_session:
            session.close()

    if response.status_code >= 400 and (debug or show_http_request):
        print(
            f"[http] Response {response.status_code} {response.reason} for {prepared.method} {prepared.url}",
            file=sys.stderr,
        )
        body_text = response.text
        if body_text:
            print(body_text, file=sys.stderr)
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
    session: requests.Session | None = None,
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
            session=session,
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


def get_config_table(config: dict[str, Any]) -> dict[str, Any]:
    # Back-compat: accept multiple spellings.
    for key in ("ipam_to_security", "ipamtosecurity", "ipam-to-security"):
        table = config.get(key)
        if table is None:
            continue
        if isinstance(table, dict):
            return table
        raise RuntimeError(f"Config {key} must be a table.")
    return {}


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


def parse_boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off", ""}:
            return False
    return None


def is_security_sync_disabled(record: dict[str, Any], disable_field: str) -> bool:
    custom_fields = record.get("custom_fields")
    if not isinstance(custom_fields, dict):
        return False
    value = custom_fields.get(disable_field)
    parsed = parse_boolish(value)
    return parsed is True


def build_security_payload(
    record: dict[str, Any],
    backref_field: str,
    base_url: str,
    debug: bool,
    managed_slug: str,
    existing_security_record: dict[str, Any] | None = None,
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

    if existing_security_record is None:
        payload["tags"] = [{"slug": managed_slug}]
    else:
        payload["tags"] = tags_payload_from_slugs(
            merged_tag_list(existing_security_record, managed_slug)
        )
    
    if dns_name:
        payload["dns_name"] = dns_name
    
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


def normalize_tag_slugs(tags_value: Any) -> list[str]:
    if not tags_value:
        return []
    if isinstance(tags_value, list):
        slugs: list[str] = []
        for item in tags_value:
            if isinstance(item, str) and item:
                slugs.append(item)
            elif isinstance(item, dict):
                slug = item.get("slug")
                if isinstance(slug, str) and slug:
                    slugs.append(slug)
        return slugs
    return []


def tags_payload_from_slugs(slugs: list[str]) -> list[dict[str, str]]:
    # Some NetBox plugin endpoints require tags as related objects (dicts), not raw slugs.
    return [{"slug": slug} for slug in slugs if isinstance(slug, str) and slug]


def merged_tag_list(existing_record: dict[str, Any], managed_slug: str) -> list[str]:
    existing_slugs = normalize_tag_slugs(existing_record.get("tags"))
    union = set(existing_slugs)
    union.add(managed_slug)
    return sorted(union)


def resolve_tag_slug(
    tag_name: str,
    base_url: str,
    headers: dict[str, str],
    debug: bool,
    show_http_request: bool,
    cache: dict[str, str],
    session: requests.Session,
) -> str:
    if tag_name in cache:
        return cache[tag_name]

    url = build_api_url(base_url, EXTRAS_TAGS_ENDPOINT, debug)
    params = {"name": tag_name, "limit": "200"}
    payload = request_json(
        "GET",
        url,
        headers,
        params,
        None,
        debug,
        show_http_request,
        session=session,
    )

    results: list[Any] = []
    if isinstance(payload, dict):
        maybe_results = payload.get("results")
        if isinstance(maybe_results, list):
            results = maybe_results
    elif isinstance(payload, list):
        results = payload

    for item in results:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug")
        name = item.get("name")
        if name == tag_name and isinstance(slug, str) and slug:
            cache[tag_name] = slug
            if debug:
                print(f"[debug] Resolved tag '{tag_name}' -> slug '{slug}'", file=sys.stderr)
            return slug

    raise RuntimeError(f"Tag not found: {tag_name}")


def collect_primary_ip4_by_tag(
    base_url: str,
    headers: dict[str, str],
    limit: int,
    tag_slug: str,
    strict: bool,
    debug: bool,
    show_http_request: bool,
    session: requests.Session,
) -> set[str]:
    params = {"tag": tag_slug, "limit": str(limit)}
    endpoints = (VMS_ENDPOINT, DEVICES_ENDPOINT)
    ips: set[str] = set()

    for endpoint in endpoints:
        url = build_api_url(base_url, endpoint, debug)
        records = fetch_all_records(
            url,
            headers,
            params,
            debug,
            show_http_request,
            session=session,
        )
        for record in records:
            record_id = record.get("id")
            primary = record.get("primary_ip4")
            if isinstance(primary, dict):
                addr = primary.get("address")
                if isinstance(addr, str) and addr:
                    ips.add(normalize_security_address(addr, debug, record_id))
                    continue

            if strict:
                name = record.get("name")
                display = name if isinstance(name, str) else str(record_id)
                raise RuntimeError(
                    f"Missing primary_ip4.address for tagged object '{display}' (tag={tag_slug})"
                )
            if debug:
                name = record.get("name")
                display = name if isinstance(name, str) else str(record_id)
                print(
                    f"[debug] Skipping tagged object without primary_ip4.address: {display}",
                    file=sys.stderr,
                )

    return ips


def build_desired_dest_sets(
    services: list[dict[str, Any]],
    require_service_ip_binding: bool,
    strict: bool,
    debug: bool,
) -> dict[str, set[str]]:
    desired: dict[str, set[str]] = {}
    for service in services:
        service_id = service.get("id")
        custom_fields = service.get("custom_fields")
        if not isinstance(custom_fields, dict):
            custom_fields = {}

        ingress = custom_fields.get("ingress")
        exposure = custom_fields.get("exposure")

        if not isinstance(ingress, str) or not ingress:
            msg = f"Service missing custom_fields.ingress: {service_id}"
            if strict:
                raise RuntimeError(msg)
            if debug:
                print(f"[debug] {msg}", file=sys.stderr)
            continue
        if not isinstance(exposure, str) or not exposure:
            msg = f"Service missing custom_fields.exposure: {service_id}"
            if strict:
                raise RuntimeError(msg)
            if debug:
                print(f"[debug] {msg}", file=sys.stderr)
            continue

        protocol = service.get("protocol")
        proto = None
        if isinstance(protocol, dict):
            value = protocol.get("value")
            if isinstance(value, str) and value:
                proto = value
        if not proto:
            msg = f"Service missing protocol.value: {service_id}"
            if strict:
                raise RuntimeError(msg)
            if debug:
                print(f"[debug] {msg}", file=sys.stderr)
            continue

        ports = service.get("ports")
        if not isinstance(ports, list) or not ports:
            msg = f"Service missing ports: {service_id}"
            if strict:
                raise RuntimeError(msg)
            if debug:
                print(f"[debug] {msg}", file=sys.stderr)
            continue

        ipaddresses = service.get("ipaddresses")
        if not isinstance(ipaddresses, list):
            ipaddresses = []
        if require_service_ip_binding and not ipaddresses:
            msg = f"Service has no bound ipaddresses: {service_id}"
            if strict:
                raise RuntimeError(msg)
            if debug:
                print(f"[debug] {msg}", file=sys.stderr)
            continue

        member_ips: list[str] = []
        for ip_obj in ipaddresses:
            if not isinstance(ip_obj, dict):
                continue
            addr = ip_obj.get("address")
            if isinstance(addr, str) and addr:
                member_ips.append(normalize_security_address(addr, debug, service_id))

        for port in ports:
            setname = f"as_{exposure}_{ingress}_{proto}_{port}"
            desired.setdefault(setname, set()).update(member_ips)

    return desired


def build_security_address_maps(
    security_records: list[dict[str, Any]],
    debug: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    by_address: dict[str, dict[str, Any]] = {}
    id_by_address: dict[str, int] = {}
    for record in security_records:
        address = record.get("address")
        if not isinstance(address, str) or not address:
            continue
        normalized = normalize_security_address(address, debug, record.get("id"))
        record_id = record.get("id")
        if isinstance(record_id, int):
            by_address[normalized] = record
            id_by_address[normalized] = record_id
    return by_address, id_by_address


def extract_existing_addressset_member_ids(record: dict[str, Any]) -> list[int]:
    addresses = record.get("addresses")
    ids: list[int] = []
    if isinstance(addresses, list):
        for item in addresses:
            if isinstance(item, int):
                ids.append(item)
            elif isinstance(item, dict):
                item_id = item.get("id")
                if isinstance(item_id, int):
                    ids.append(item_id)
    return sorted(set(ids))


def build_addressset_payload(
    name: str,
    member_ids: list[int],
    managed_slug: str,
    existing_record: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "addresses": member_ids,
    }
    if existing_record is None:
        payload["address_sets"] = []
        payload["description"] = "managed-by-script"
        payload["tags"] = [{"slug": managed_slug}]
    else:
        payload["tags"] = tags_payload_from_slugs(
            merged_tag_list(existing_record, managed_slug)
        )
        desc = existing_record.get("description")
        if not isinstance(desc, str) or not desc.strip():
            payload["description"] = "managed-by-script"
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync NetBox IPAM IP Addresses to Security Addresses with backreferences."
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
        "--disable-sync-field",
        default="disable_security_sync",
        help=(
            "NetBox IP Address custom field name (boolean) which disables syncing when true "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create/update NetBox Security addresses",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update existing Security addresses when backref matches",
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
        "--addresssets-endpoint",
        default=None,
        help=(
            "Security address-sets API endpoint (default: config or "
            "/api/plugins/netbox-security/address-sets/)"
        ),
    )
    parser.add_argument(
        "--managed-tag",
        default="managed-by-script",
        help="Tag name to enforce on created/updated Security objects",
    )
    parser.add_argument(
        "--role-caddy-tag",
        default="role:caddy-proxy",
        help="Tag name identifying Caddy proxy nodes",
    )
    parser.add_argument(
        "--role-subnet-router-tag",
        default="role:tailscale-subnet-router",
        help="Tag name identifying Tailscale subnet router nodes",
    )
    parser.add_argument(
        "--require-service-ip-binding",
        action="store_true",
        help=(
            "Require IPAM Services to have bound IP addresses (service.ipaddresses). "
            "When set, services without bindings are skipped; with --strict they fail the run."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Treat missing/invalid source data as a fatal error (recommended for firewall automation). "
            "Without this flag, the script skips problematic records with debug logging."
        ),
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
    try:
        ipam_to_security_config = get_config_table(config)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    
    # Load config defaults
    default_limit = parser.get_default("limit")
    default_backref_field = parser.get_default("backref_field")
    default_disable_sync_field = parser.get_default("disable_sync_field")
    
    config_limit = ipam_to_security_config.get("limit")
    if isinstance(config_limit, int) and args.limit == default_limit:
        args.limit = config_limit
    
    config_backref_field = ipam_to_security_config.get("backref_field")
    if isinstance(config_backref_field, str) and args.backref_field == default_backref_field:
        args.backref_field = config_backref_field

    config_disable_sync_field = (
        ipam_to_security_config.get("disable_sync_field")
        or ipam_to_security_config.get("disable_security_sync_field")
    )
    if isinstance(config_disable_sync_field, str) and args.disable_sync_field == default_disable_sync_field:
        args.disable_sync_field = config_disable_sync_field

    # String defaults from config
    for key in (
        "managed_tag",
        "role_caddy_tag",
        "role_subnet_router_tag",
        "addresssets_endpoint",
    ):
        config_value = ipam_to_security_config.get(key)
        if isinstance(config_value, str) and config_value:
            current = getattr(args, key, None)
            if current == parser.get_default(key):
                setattr(args, key, config_value)

    # Booleans that can be made true by config
    for flag_name in (
        "apply",
        "update",
        "show_payload",
        "show_http_request",
        "suppress_insecure_warning",
        "debug",
        "require_service_ip_binding",
        "strict",
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
        or SECURITY_ADDRESSES_ENDPOINT
    )
    security_url = build_security_url(base_url, security_endpoint, args.debug)

    addresssets_endpoint = (
        args.addresssets_endpoint
        or ipam_to_security_config.get("addresssets_endpoint")
        or ipam_to_security_config.get("address_sets_endpoint")
        or config.get("netbox_security_address_sets_endpoint")
        or SECURITY_ADDRESSSETS_ENDPOINT
    )
    addresssets_url = build_security_url(base_url, addresssets_endpoint, args.debug)
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    # Resolve tag slugs at startup
    session = requests.Session()
    tag_cache: dict[str, str] = {}
    try:
        managed_slug = resolve_tag_slug(
            args.managed_tag,
            base_url,
            headers,
            args.debug,
            args.show_http_request,
            tag_cache,
            session,
        )
        role_caddy_slug = resolve_tag_slug(
            args.role_caddy_tag,
            base_url,
            headers,
            args.debug,
            args.show_http_request,
            tag_cache,
            session,
        )
        role_subnet_router_slug = resolve_tag_slug(
            args.role_subnet_router_tag,
            base_url,
            headers,
            args.debug,
            args.show_http_request,
            tag_cache,
            session,
        )
    except (requests.RequestException, RuntimeError) as exc:
        print(f"Tag resolution failed: {exc}", file=sys.stderr)
        session.close()
        return 1
    
    base_params: dict[str, str] = {
        "limit": str(args.limit),
    }
    
    # =========================
    # Phase A: Sync Addresses
    # =========================
    try:
        ipam_records = fetch_all_records(
            ipam_url,
            headers,
            base_params,
            args.debug,
            args.show_http_request,
            session=session,
        )
    except requests.RequestException as exc:
        print(f"IPAM request failed: {exc}", file=sys.stderr)
        session.close()
        return 1
    except RuntimeError as exc:
        print(f"Unexpected IPAM response: {exc}", file=sys.stderr)
        session.close()
        return 1

    security_params: dict[str, str] = {"limit": str(args.limit)}
    try:
        security_records = fetch_all_records(
            security_url,
            headers,
            security_params,
            args.debug,
            args.show_http_request,
            session=session,
        )
    except requests.RequestException as exc:
        print(f"Security request failed: {exc}", file=sys.stderr)
        session.close()
        return 1
    except RuntimeError as exc:
        print(f"Unexpected security response: {exc}", file=sys.stderr)
        session.close()
        return 1

    existing_by_backref: dict[str, dict[str, Any]] = {}
    for record in security_records:
        backref_value = extract_backref_value(record, args.backref_field, base_url)
        if backref_value:
            existing_by_backref[backref_value] = record

    if args.debug:
        print(
            f"[debug] Loaded {len(existing_by_backref)} Security addresses by backref",
            file=sys.stderr,
        )

    created = 0
    updated = 0
    skipped = 0

    for record in ipam_records:
        if args.disable_sync_field and is_security_sync_disabled(record, args.disable_sync_field):
            skipped += 1
            address = record.get("address")
            dns_name = record.get("dns_name")
            display = dns_name if isinstance(dns_name, str) and dns_name else ""
            display = display or (address if isinstance(address, str) else "")
            address_str = address if isinstance(address, str) else ""
            print(f"SKIP\tDISABLED\t{display}\t{address_str}\t{record.get('id')}")
            continue

        backref_value = build_backref(record, base_url)
        existing = existing_by_backref.get(backref_value) if backref_value else None

        payload = build_security_payload(
            record,
            args.backref_field,
            base_url,
            args.debug,
            managed_slug,
            existing_security_record=existing,
        )
        if payload is None:
            skipped += 1
            continue

        # If existing is present but backref mismatch somehow, try to recompute from payload.
        if not backref_value:
            custom_fields = payload.get("custom_fields")
            if isinstance(custom_fields, dict):
                value = custom_fields.get(args.backref_field)
                if isinstance(value, str) and value:
                    backref_value = value

        if existing:
            if not args.update:
                skipped += 1
                print(f"SKIP\t{payload['name']}\t{payload['address']}\t{backref_value}")
                continue

            target_url = existing.get("url")
            if not isinstance(target_url, str) or not target_url:
                record_id = existing.get("id")
                target_url = f"{security_url.rstrip('/')}/{record_id}/"

            if args.apply:
                try:
                    if args.show_payload:
                        print(f"PAYLOAD\tUPDATE\t{json.dumps(payload, sort_keys=True)}")

                    updated_record = request_json(
                        "PATCH",
                        target_url,
                        headers,
                        None,
                        payload,
                        args.debug,
                        args.show_http_request,
                        session=session,
                    )
                    if isinstance(updated_record, dict) and backref_value:
                        existing_by_backref[backref_value] = updated_record
                except requests.RequestException as exc:
                    print(f"Update failed: {exc}", file=sys.stderr)
                    session.close()
                    return 1

            updated += 1
            print(f"UPDATE\t{payload['name']}\t{payload['address']}\t{backref_value}")
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
                    session=session,
                )
                if isinstance(created_record, dict) and backref_value:
                    existing_by_backref[backref_value] = created_record
            except requests.RequestException as exc:
                print(f"Create failed: {exc}", file=sys.stderr)
                session.close()
                return 1

        created += 1
        print(f"CREATE\t{payload['name']}\t{payload['address']}\t{backref_value}")

    print(f"Address Summary: created={created} updated={updated} skipped={skipped}")

    # Re-fetch Security addresses after apply, so AddressSets can reference fresh IDs.
    if args.apply and (created > 0 or updated > 0):
        try:
            security_records = fetch_all_records(
                security_url,
                headers,
                security_params,
                args.debug,
                args.show_http_request,
                session=session,
            )
        except requests.RequestException as exc:
            print(f"Security re-fetch failed: {exc}", file=sys.stderr)
            session.close()
            return 1
        except RuntimeError as exc:
            print(f"Unexpected security response: {exc}", file=sys.stderr)
            session.close()
            return 1

    # =========================
    # Phase B: Build AddressSets
    # =========================
    _, security_addr_id_by_address = build_security_address_maps(security_records, args.debug)

    services_url = build_api_url(base_url, IPAM_SERVICES_ENDPOINT, args.debug)
    try:
        services = fetch_all_records(
            services_url,
            headers,
            {"limit": str(args.limit)},
            args.debug,
            args.show_http_request,
            session=session,
        )
    except requests.RequestException as exc:
        print(f"Services request failed: {exc}", file=sys.stderr)
        session.close()
        return 1
    except RuntimeError as exc:
        print(f"Unexpected services response: {exc}", file=sys.stderr)
        session.close()
        return 1

    try:
        desired_dest_sets = build_desired_dest_sets(
            services,
            require_service_ip_binding=args.require_service_ip_binding,
            strict=args.strict,
            debug=args.debug,
        )
    except RuntimeError as exc:
        print(f"AddressSet build failed: {exc}", file=sys.stderr)
        session.close()
        return 1

    try:
        caddy_ips = collect_primary_ip4_by_tag(
            base_url,
            headers,
            args.limit,
            role_caddy_slug,
            args.strict,
            args.debug,
            args.show_http_request,
            session,
        )
        subnet_router_ips = collect_primary_ip4_by_tag(
            base_url,
            headers,
            args.limit,
            role_subnet_router_slug,
            args.strict,
            args.debug,
            args.show_http_request,
            session,
        )
    except (requests.RequestException, RuntimeError) as exc:
        print(f"Role IP collection failed: {exc}", file=sys.stderr)
        session.close()
        return 1

    desired_src_sets: dict[str, set[str]] = {
        "as_src_caddy_proxies": caddy_ips,
        "as_src_trusted_tailnet_snat": subnet_router_ips,
    }

    desired_sets: dict[str, set[str]] = {}
    desired_sets.update(desired_dest_sets)
    desired_sets.update(desired_src_sets)

    # =========================
    # Phase C: Sync AddressSets
    # =========================
    try:
        existing_sets = fetch_all_records(
            addresssets_url,
            headers,
            {"limit": str(args.limit)},
            args.debug,
            args.show_http_request,
            session=session,
        )
    except requests.RequestException as exc:
        print(f"AddressSets request failed: {exc}", file=sys.stderr)
        session.close()
        return 1
    except RuntimeError as exc:
        print(f"Unexpected address-sets response: {exc}", file=sys.stderr)
        session.close()
        return 1

    existing_by_name: dict[str, dict[str, Any]] = {}
    for rec in existing_sets:
        name = rec.get("name")
        if isinstance(name, str) and name:
            existing_by_name[name] = rec

    set_created = 0
    set_updated = 0
    set_skipped = 0

    for set_name, member_ips in sorted(desired_sets.items()):
        desired_member_ids: list[int] = []
        missing_members: list[str] = []
        for ip in sorted(member_ips):
            member_id = security_addr_id_by_address.get(ip)
            if member_id is None:
                missing_members.append(ip)
            else:
                desired_member_ids.append(member_id)

        desired_member_ids = sorted(set(desired_member_ids))

        if missing_members:
            msg = f"Missing Security Address for {set_name}: {', '.join(missing_members)}"
            if args.strict:
                print(msg, file=sys.stderr)
                session.close()
                return 1
            if args.debug:
                print(f"[debug] {msg}", file=sys.stderr)
            set_skipped += 1
            print(f"SKIP-SET\t{set_name}\tmembers={len(desired_member_ids)}\treason=missing-members")
            continue

        existing = existing_by_name.get(set_name)
        if existing is None:
            payload = build_addressset_payload(
                set_name,
                desired_member_ids,
                managed_slug,
                existing_record=None,
            )
            if args.apply:
                try:
                    if args.show_payload:
                        print(f"PAYLOAD\tCREATE-SET\t{json.dumps(payload, sort_keys=True)}")
                    _ = request_json(
                        "POST",
                        addresssets_url,
                        headers,
                        None,
                        payload,
                        args.debug,
                        args.show_http_request,
                        session=session,
                    )
                except requests.RequestException as exc:
                    print(f"Create AddressSet failed: {exc}", file=sys.stderr)
                    session.close()
                    return 1
            set_created += 1
            print(f"CREATE-SET\t{set_name}\tmembers={len(desired_member_ids)}")
            continue

        if not args.update:
            set_skipped += 1
            print(f"SKIP-SET\t{set_name}\tmembers={len(desired_member_ids)}\treason=update-disabled")
            continue

        existing_member_ids = extract_existing_addressset_member_ids(existing)
        desired_tags = merged_tag_list(existing, managed_slug)
        existing_tags = sorted(set(normalize_tag_slugs(existing.get("tags"))))

        changed_members = existing_member_ids != desired_member_ids
        changed_tags = existing_tags != desired_tags

        existing_desc = existing.get("description")
        should_set_desc = not (isinstance(existing_desc, str) and existing_desc.strip())
        changed_desc = should_set_desc

        if not (changed_members or changed_tags or changed_desc):
            set_skipped += 1
            print(f"SKIP-SET\t{set_name}\tmembers={len(desired_member_ids)}")
            continue

        payload = build_addressset_payload(
            set_name,
            desired_member_ids,
            managed_slug,
            existing_record=existing,
        )

        changed_parts: list[str] = []
        if changed_members:
            changed_parts.append("members")
        if changed_tags:
            changed_parts.append("tags")
        if changed_desc:
            changed_parts.append("desc")

        target_url = existing.get("url")
        if not isinstance(target_url, str) or not target_url:
            record_id = existing.get("id")
            target_url = f"{addresssets_url.rstrip('/')}/{record_id}/"

        if args.apply:
            try:
                if args.show_payload:
                    print(f"PAYLOAD\tUPDATE-SET\t{json.dumps(payload, sort_keys=True)}")
                _ = request_json(
                    "PATCH",
                    target_url,
                    headers,
                    None,
                    payload,
                    args.debug,
                    args.show_http_request,
                    session=session,
                )
            except requests.RequestException as exc:
                print(f"Update AddressSet failed: {exc}", file=sys.stderr)
                session.close()
                return 1

        set_updated += 1
        print(
            f"UPDATE-SET\t{set_name}\tmembers={len(desired_member_ids)}\tchanged={('|'.join(changed_parts))}"
        )

    print(
        f"AddressSet Summary: created={set_created} updated={set_updated} skipped={set_skipped}"
    )
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
