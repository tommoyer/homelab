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


TagParams = dict[str, str] | list[tuple[str, str]] | None


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    params: TagParams,
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
    params: TagParams,
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


def normalize_tag_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of strings")
    normalized: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError(f"{label} must contain only strings")
        stripped = entry.strip()
        if stripped:
            normalized.append(stripped)
    return normalized


def build_tag_params(
    limit: int,
    managed_tags_all: list[str],
    intent_tag: str | None,
) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = [("limit", str(limit))]
    for tag in managed_tags_all:
        params.append(("tag", tag))
    if intent_tag:
        params.append(("tag", intent_tag))
    return params


def fetch_records_for_intent_tags(
    url: str,
    headers: dict[str, str],
    limit: int,
    managed_tags_all: list[str],
    intent_tags_any: list[str],
    debug: bool,
    show_http_request: bool,
) -> list[dict[str, Any]]:
    all_records: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    if intent_tags_any:
        for intent_tag in intent_tags_any:
            params = build_tag_params(limit, managed_tags_all, intent_tag)
            records = fetch_all_records(
                url, headers, params, debug, show_http_request
            )
            for record in records:
                record_id = record.get("id")
                if isinstance(record_id, int):
                    if record_id in seen_ids:
                        continue
                    seen_ids.add(record_id)
                all_records.append(record)
        return all_records
    params = build_tag_params(limit, managed_tags_all, None)
    return fetch_all_records(url, headers, params, debug, show_http_request)


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
        return canonicalize_ipam_backref(value[len(base_url) :])
    return canonicalize_ipam_backref(value)


def build_backref(record: dict[str, Any], base_url: str) -> str | None:
    backref = record.get("display_url") or record.get("url")
    if isinstance(backref, str) and backref:
        return normalize_backref(backref, base_url.rstrip("/"))
    return None


def build_security_payload(
    record: dict[str, Any],
    backref_field: str,
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
    return payload


def normalize_security_address(address: str, debug: bool, record_id: Any) -> str:
    try:
        interface = ipaddress.ip_interface(address)
    except ValueError:
        if debug:
            print(
                f"[debug] Invalid address '{address}' for record {record_id}",
                file=sys.stderr,
            )
        return address
    if interface.version == 4 and interface.network.prefixlen == 24:
        return f"{interface.ip}/32"
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
        legacy_tag = entry.get("tag") or entry.get("tag_slug")
        intent_tags_any = normalize_tag_list(
            entry.get("intent_tags_any"), "address_sets.intent_tags_any"
        )
        if not intent_tags_any and legacy_tag:
            intent_tags_any = [str(legacy_tag)]
        name = entry.get("address_set") or entry.get("name")
        sources = entry.get("sources") or entry.get("source")
        if not intent_tags_any or not name:
            raise ValueError(
                "address_sets entries require intent_tags_any and address_set"
            )
        if sources is None:
            sources = ["services", "devices"]
        if isinstance(sources, str):
            sources = [sources]
        if not isinstance(sources, list):
            raise ValueError("address_sets sources must be a list")
        normalized_sources = [str(item).strip().lower() for item in sources if item]
        backref_tag = str(legacy_tag) if legacy_tag else None
        if not backref_tag and len(intent_tags_any) == 1:
            backref_tag = intent_tags_any[0]
        mappings.append(
            {
                "intent_tags_any": intent_tags_any,
                "backref_tag": backref_tag,
                "name": str(name),
                "sources": normalized_sources,
            }
        )
    if debug:
        print(
            f"[debug] Loaded {len(mappings)} service address set mappings",
            file=sys.stderr,
        )
    return mappings


def build_tag_backref(tag: str) -> str:
    return f"/api/extras/tags/?slug={urllib.parse.quote(tag)}"


def build_address_set_payload(
    name: str,
    address_ids: list[int],
    backref_field: str,
    backref_value: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "addresses": sorted(set(address_ids)),
    }
    if backref_value:
        payload["custom_fields"] = {backref_field: backref_value}
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
    backref_field: str,
    base_url: str,
    security_url: str,
    headers: dict[str, str],
    apply_changes: bool,
    show_payload: bool,
    debug: bool,
    show_http_request: bool,
) -> int | None:
    payload = build_security_payload(record, backref_field, base_url, debug)
    if payload is None:
        return None
    backref_value = None
    custom_fields = payload.get("custom_fields")
    if isinstance(custom_fields, dict):
        value = custom_fields.get(backref_field)
        if isinstance(value, str) and value:
            backref_value = value
    if backref_value:
        existing = existing_by_backref.get(backref_value)
        if existing:
            record_id = existing.get("id")
            if isinstance(record_id, int):
                if debug:
                    print(
                        f"[debug] Found Security address {record_id} for backref {backref_value}",
                        file=sys.stderr,
                    )
                return record_id
            if debug:
                print(
                    f"[debug] Security address for backref {backref_value} missing id",
                    file=sys.stderr,
                )
        elif debug:
            print(
                f"[debug] No Security address for backref {backref_value}",
                file=sys.stderr,
            )
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
        record_id = created.get("id")
        if isinstance(record_id, int):
            return record_id
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync NetBox IP addresses tagged sec:sync to Security addresses."
    )
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "config.toml"),
        help="Path to TOML config (default: %(default)s)",
    )
    parser.add_argument(
        "--tag",
        default="secsync",
        help="Legacy NetBox tag slug to filter by (default: %(default)s)",
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

    default_tag = parser.get_default("tag")
    default_limit = parser.get_default("limit")
    default_backref_field = parser.get_default("backref_field")

    config_tag = ipam_to_security_config.get("tag")
    if isinstance(config_tag, str) and args.tag == default_tag:
        args.tag = config_tag
    config_limit = ipam_to_security_config.get("limit")
    if isinstance(config_limit, int) and args.limit == default_limit:
        args.limit = config_limit
    config_backref_field = ipam_to_security_config.get("backref_field")
    if isinstance(config_backref_field, str) and args.backref_field == default_backref_field:
        args.backref_field = config_backref_field

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

    try:
        managed_tags_all = normalize_tag_list(
            ipam_to_security_config.get("managed_tags_all"),
            "ipam_to_security.managed_tags_all",
        )
        intent_tags_any = normalize_tag_list(
            ipam_to_security_config.get("intent_tags_any"),
            "ipam_to_security.intent_tags_any",
        )
    except ValueError as exc:
        print(f"Invalid tag configuration: {exc}", file=sys.stderr)
        return 2
    if not intent_tags_any:
        if isinstance(config_tag, str) and args.tag == default_tag:
            intent_tags_any = [config_tag]
        elif args.tag != default_tag:
            intent_tags_any = [args.tag]

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
    security_params: dict[str, str] = {"limit": str(args.limit)}

    try:
        ipam_records = fetch_records_for_intent_tags(
            ipam_url,
            headers,
            args.limit,
            managed_tags_all,
            intent_tags_any,
            args.debug,
            args.show_http_request,
        )
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Unexpected response: {exc}", file=sys.stderr)
        return 1

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

    existing_by_backref: dict[str, dict[str, Any]] = {}
    for record in security_records:
        backref_value = extract_backref_value(record, args.backref_field, base_url)
        if backref_value:
            existing_by_backref[backref_value] = record

    created = 0
    updated = 0
    skipped = 0
    for record in ipam_records:
        payload = build_security_payload(record, args.backref_field, base_url, args.debug)
        if payload is None:
            skipped += 1
            continue

        backref_value = None
        custom_fields = payload.get("custom_fields")
        if isinstance(custom_fields, dict):
            value = custom_fields.get(args.backref_field)
            if isinstance(value, str) and value:
                backref_value = value

        existing = existing_by_backref.get(backref_value) if backref_value else None
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
                    if isinstance(updated_record, dict) and backref_value:
                        existing_by_backref[backref_value] = updated_record
                except requests.RequestException as exc:
                    print(f"Update failed: {exc}", file=sys.stderr)
                    return 1
            updated += 1
            print(f"UPDATE\t{payload['name']}\t{payload['address']}\t{backref_value}")
            continue

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
                if isinstance(created_record, dict) and backref_value:
                    existing_by_backref[backref_value] = created_record
            except requests.RequestException as exc:
                print(f"Create failed: {exc}", file=sys.stderr)
                return 1
        created += 1
        print(f"CREATE\t{payload['name']}\t{payload['address']}\t{backref_value}")

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

        existing_sets_by_backref: dict[str, dict[str, Any]] = {}
        existing_sets_by_name: dict[str, dict[str, Any]] = {}
        for record in address_sets:
            backref_value = extract_backref_value(
                record, address_set_backref_field, base_url
            )
            if backref_value:
                existing_sets_by_backref[backref_value] = record
            name = record.get("name")
            if isinstance(name, str) and name:
                existing_sets_by_name[name] = record

        devices_url = build_devices_url(base_url, args.debug)
        for mapping in service_address_sets:
            intent_tags_any = mapping["intent_tags_any"]
            backref_tag = mapping.get("backref_tag")
            set_name = mapping["name"]
            sources = mapping.get("sources") or []
            if args.debug:
                print(
                    f"[debug] Building AddressSet '{set_name}' from intent tags {intent_tags_any}",
                    file=sys.stderr,
                )
            address_ids: list[int] = []
            missing_ids = 0
            for source in sources:
                if source == "services":
                    try:
                        services = fetch_records_for_intent_tags(
                            services_url,
                            headers,
                            args.limit,
                            managed_tags_all,
                            intent_tags_any,
                            args.debug,
                            args.show_http_request,
                        )
                    except requests.RequestException as exc:
                        print(f"Services request failed: {exc}", file=sys.stderr)
                        return 1
                    except RuntimeError as exc:
                        print(f"Unexpected services response: {exc}", file=sys.stderr)
                        return 1
                    for service in services:
                        for ip_record in extract_service_ipaddresses(
                            service, args.debug
                        ):
                            address_id = get_security_address_id(
                                ip_record,
                                existing_by_backref,
                                args.backref_field,
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
                    try:
                        devices = fetch_records_for_intent_tags(
                            devices_url,
                            headers,
                            args.limit,
                            managed_tags_all,
                            intent_tags_any,
                            args.debug,
                            args.show_http_request,
                        )
                    except requests.RequestException as exc:
                        print(f"Devices request failed: {exc}", file=sys.stderr)
                        return 1
                    except RuntimeError as exc:
                        print(f"Unexpected devices response: {exc}", file=sys.stderr)
                        return 1
                    for device in devices:
                        for ip_record in extract_device_ipaddresses(
                            device, args.debug
                        ):
                            address_id = get_security_address_id(
                                ip_record,
                                existing_by_backref,
                                args.backref_field,
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

            backref_value = build_tag_backref(backref_tag) if backref_tag else ""
            payload = build_address_set_payload(
                set_name, address_ids, address_set_backref_field, backref_value
            )
            existing_set = existing_sets_by_backref.get(backref_value)
            if not existing_set:
                existing_set = existing_sets_by_name.get(set_name)
            if existing_set:
                if not args.update:
                    address_set_skipped += 1
                    print(
                        f"ADDRSET\tSKIP\t{set_name}\t{','.join(intent_tags_any)}\t{len(address_ids)}"
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
                                "PAYLOAD\tADDRESSSET\tUPDATE\t"
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
                            existing_sets_by_backref[backref_value] = updated_record
                            existing_sets_by_name[set_name] = updated_record
                    except requests.RequestException as exc:
                        print(f"Address set update failed: {exc}", file=sys.stderr)
                        return 1
                address_set_updated += 1
                print(
                    f"ADDRSET\tUPDATE\t{set_name}\t{','.join(intent_tags_any)}\t{len(address_ids)}"
                )
                continue

            if args.apply:
                try:
                    if args.show_payload:
                        print(
                            "PAYLOAD\tADDRESSSET\tCREATE\t"
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
                        existing_sets_by_backref[backref_value] = created_record
                        existing_sets_by_name[set_name] = created_record
                except requests.RequestException as exc:
                    print(f"Address set create failed: {exc}", file=sys.stderr)
                    return 1
            address_set_created += 1
            print(
                f"ADDRSET\tCREATE\t{set_name}\t{','.join(intent_tags_any)}\t{len(address_ids)}"
            )

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
