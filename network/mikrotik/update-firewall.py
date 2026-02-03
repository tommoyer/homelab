#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
import subprocess
import sys
import tempfile
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


def build_url(base_url: str, debug: bool) -> str:
    url = f"{base_url.rstrip('/')}/api/plugins/custom-objects/firewall-policies/"
    if debug:
        print(f"[debug] Built NetBox URL: {url}", file=sys.stderr)
    return url


def build_services_url(base_url: str, debug: bool) -> str:
    url = f"{base_url.rstrip('/')}/api/ipam/services/"
    if debug:
        print(f"[debug] Built NetBox services URL: {url}", file=sys.stderr)
    return url


def request_json(
    url: str,
    headers: dict[str, str],
    params: dict[str, str] | None,
    debug: bool,
) -> Any:
    if debug:
        print(f"[debug] Requesting {url} params={params}", file=sys.stderr)
    response = requests.get(url, headers=headers, params=params, timeout=30, verify=False)
    response.raise_for_status()
    return response.json()


def fetch_all_records(
    url: str,
    headers: dict[str, str],
    params: dict[str, str],
    debug: bool,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    next_url: str | None = url
    next_params: dict[str, str] | None = params

    while next_url:
        payload = request_json(next_url, headers, next_params, debug)
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


def build_service_map(
    services: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    service_map: dict[int, dict[str, Any]] = {}
    for service in services:
        service_id = service.get("id")
        if isinstance(service_id, int):
            service_map[service_id] = service
    return service_map


def normalize_ports(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        ports: list[int] = []
        for item in value:
            if isinstance(item, int):
                ports.append(item)
            elif isinstance(item, str) and item.isdigit():
                ports.append(int(item))
        return ports
    if isinstance(value, int):
        return [value]
    if isinstance(value, str) and value.isdigit():
        return [int(value)]
    return []


def normalize_protocol(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        return value.lower()
    return None


def normalize_ip(address: str) -> str | None:
    try:
        return str(ipaddress.ip_interface(address).ip)
    except ValueError:
        return None


def extract_ipaddresses(service: dict[str, Any]) -> list[str]:
    ipaddresses = service.get("ipaddresses", [])
    if not isinstance(ipaddresses, list):
        return []
    resolved: list[str] = []
    for item in ipaddresses:
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        if not isinstance(address, str):
            continue
        normalized = normalize_ip(address)
        if normalized:
            resolved.append(normalized)
    return resolved


def normalize_network(prefix: str) -> str | None:
    try:
        return str(ipaddress.ip_network(prefix, strict=False))
    except ValueError:
        return None


def extract_ip_field(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        address = value.get("address")
        if isinstance(address, str):
            normalized = normalize_ip(address)
            return [normalized] if normalized else []
    if isinstance(value, list):
        addresses: list[str] = []
        for item in value:
            addresses.extend(extract_ip_field(item))
        return addresses
    if isinstance(value, str):
        normalized = normalize_ip(value)
        return [normalized] if normalized else []
    return []


def extract_prefix_field(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        prefix = value.get("prefix")
        if isinstance(prefix, str):
            normalized = normalize_network(prefix)
            return [normalized] if normalized else []
    if isinstance(value, list):
        prefixes: list[str] = []
        for item in value:
            prefixes.extend(extract_prefix_field(item))
        return prefixes
    if isinstance(value, str):
        normalized = normalize_network(value)
        return [normalized] if normalized else []
    return []


def extract_protocol(service_ref: dict[str, Any]) -> str | None:
    proto_obj = service_ref.get("protocol")
    if isinstance(proto_obj, dict):
        proto = proto_obj.get("value") or proto_obj.get("label")
        return normalize_protocol(proto)
    if isinstance(proto_obj, str):
        return normalize_protocol(proto_obj)
    return None


def extract_ports(service_ref: dict[str, Any]) -> list[int]:
    return normalize_ports(service_ref.get("ports"))


def extract_service_ips(
    service_ref: dict[str, Any] | None,
    service_map: dict[int, dict[str, Any]],
) -> list[str]:
    if not isinstance(service_ref, dict):
        return []
    service_id = service_ref.get("id")
    if not isinstance(service_id, int):
        return []
    service = service_map.get(service_id)
    if not service:
        return []
    return extract_ipaddresses(service)


def parse_extra_args(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        return value.split()
    if isinstance(value, list):
        args: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                args.extend(item.split())
        return args
    return []


def build_firewall_rules(
    policies: list[dict[str, Any]],
    service_map: dict[int, dict[str, Any]],
    debug: bool,
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for policy in policies:
        if not policy.get("enabled", False):
            continue

        action = policy.get("action") or policy.get("policy_action") or "accept"

        chain = policy.get("chain") or policy.get("direction") or "forward"

        in_iface = None
        src_iface_dcim = policy.get("src_iface_dcim")
        if isinstance(src_iface_dcim, dict):
            in_iface = src_iface_dcim.get("name") or src_iface_dcim.get("display")
        src_iface_vm = policy.get("src_iface_vm")
        if not in_iface and isinstance(src_iface_vm, dict):
            in_iface = src_iface_vm.get("name") or src_iface_vm.get("display")

        out_iface = None
        dst_iface_dcim = policy.get("dst_iface_dcim")
        if isinstance(dst_iface_dcim, dict):
            out_iface = dst_iface_dcim.get("name") or dst_iface_dcim.get("display")
        dst_iface_vm = policy.get("dst_iface_vm")
        if not out_iface and isinstance(dst_iface_vm, dict):
            out_iface = dst_iface_vm.get("name") or dst_iface_vm.get("display")

        src_addresses = extract_ip_field(policy.get("src_ip")) or extract_prefix_field(
            policy.get("src_zone")
        )
        dst_addresses = extract_ip_field(policy.get("dst_ip")) or extract_prefix_field(
            policy.get("dst_zone")
        )
        policy_src_ports = normalize_ports(policy.get("src_port"))
        policy_dst_ports = normalize_ports(policy.get("dst_port"))
        policy_protocol = normalize_protocol(policy.get("protocol"))
        extra_args = parse_extra_args(policy.get("extra_args"))

        src_services = policy.get("src_svc", [])
        if not isinstance(src_services, list):
            src_services = []
        dst_services = policy.get("dst_svc", [])
        if not isinstance(dst_services, list):
            dst_services = []

        src_service_refs = src_services or [None]
        dst_service_refs = dst_services or [None]

        for src_ref in src_service_refs:
            src_proto = None
            src_service_ips: list[str] = []
            if isinstance(src_ref, dict):
                src_proto = extract_protocol(src_ref)
                src_service_ips = extract_service_ips(src_ref, service_map)

            for dst_ref in dst_service_refs:
                dst_ports: list[int] = []
                dst_proto = None
                dst_service_ips: list[str] = []
                if isinstance(dst_ref, dict):
                    dst_ports = extract_ports(dst_ref)
                    dst_proto = extract_protocol(dst_ref)
                    dst_service_ips = extract_service_ips(dst_ref, service_map)

                protocol = policy_protocol or src_proto or dst_proto
                if (
                    policy_protocol is None
                    and src_proto
                    and dst_proto
                    and src_proto != dst_proto
                ):
                    if debug:
                        print(
                            f"[debug] Policy {policy.get('id')} protocol mismatch; skipping",
                            file=sys.stderr,
                        )
                    continue

                resolved_src_addresses = src_addresses or src_service_ips
                resolved_dst_addresses = dst_addresses or dst_service_ips

                src_address_list = resolved_src_addresses or [None]
                dst_address_list = resolved_dst_addresses or [None]
                # For forwarded traffic, matching *source* port is almost never desired
                # (e.g. Caddy connects to upstreams using ephemeral source ports).
                # Only emit src-port if explicitly set on the policy.
                src_port_list = policy_src_ports or [None]
                dst_port_list = policy_dst_ports or dst_ports or [None]

                # ICMP has no ports; avoid generating misleading src/dst-port args.
                if protocol == "icmp":
                    src_port_list = [None]
                    dst_port_list = [None]

                for src_address in src_address_list:
                    for dst_address in dst_address_list:
                        for src_port in src_port_list:
                            for dst_port in dst_port_list:
                                rule = {
                                    "policy_id": policy.get("id"),
                                    "policy_display": policy.get("display"),
                                    "comment": policy.get("comment"),
                                    "chain": chain,
                                    "action": action,
                                    "in_interface": in_iface,
                                    "out_interface": out_iface,
                                    "protocol": protocol,
                                    "src_address": src_address,
                                    "dst_address": dst_address,
                                    "src_port": src_port,
                                    "dst_port": dst_port,
                                    "service_name": dst_ref.get("name")
                                    if isinstance(dst_ref, dict)
                                    else None,
                                    "extra_args": extra_args,
                                }
                                rules.append(rule)

    return rules


def quote_value(value: str) -> str:
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'


def render_mikrotik_rules(
    rules: list[dict[str, Any]],
    place_before_comment: str,
) -> list[str]:
    place_before_comment = (place_before_comment or "").strip()
    if not place_before_comment:
        place_before_comment = "Drop"
    place_before_exact = quote_value(place_before_comment)

    lines: list[str] = [
        '/ip firewall filter remove [find comment~"^[[]Script[]]"]',
    ]

    for rule in rules:
        parts: list[str] = [f"place-before=[find comment={place_before_exact}]"]
        chain = rule.get("chain")
        if chain:
            parts.append(f"chain={chain}")
        action = rule.get("action")
        if action:
            parts.append(f"action={action}")
        in_iface = rule.get("in_interface")
        if in_iface:
            parts.append(f"in-interface={in_iface}")
        out_iface = rule.get("out_interface")
        if out_iface:
            parts.append(f"out-interface={out_iface}")
        protocol = rule.get("protocol")
        if protocol:
            parts.append(f"protocol={protocol}")

        src_address_list = rule.get("src_address_list")
        if src_address_list:
            parts.append(f"src-address-list={src_address_list}")
        src_address = rule.get("src_address")
        if src_address:
            parts.append(f"src-address={src_address}")

        dst_address_list = rule.get("dst_address_list")
        if dst_address_list:
            parts.append(f"dst-address-list={dst_address_list}")
        dst_address = rule.get("dst_address")
        if dst_address:
            parts.append(f"dst-address={dst_address}")
        src_port = rule.get("src_port")
        if src_port is not None:
            parts.append(f"src-port={src_port}")
        dst_port = rule.get("dst_port")
        if dst_port is not None:
            parts.append(f"dst-port={dst_port}")
        extra_args = rule.get("extra_args") or []
        if isinstance(extra_args, list):
            parts.extend(str(item) for item in extra_args if item)

        comment = rule.get("comment")
        if not comment:
            comment = rule.get("policy_display") or rule.get("service_name")
        if comment:
            parts.append(f"comment={quote_value(f'[Script] {comment}')}")

        base_cmd = "/ip firewall filter add " + " ".join(parts)
        lines.append(base_cmd)
    return lines


def build_ssh_command(
    host: str,
    username: str,
    port: int | None,
) -> list[str]:
    command = [
        "ssh",
        "-T",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "PreferredAuthentications=password",
        "-o",
        "PasswordAuthentication=yes",
        "-o",
        "PubkeyAuthentication=no",
    ]
    if port:
        command.extend(["-p", str(port)])
    command.append(f"{username}@{host}")
    return command


def run_router_commands(
    host: str,
    username: str,
    port: int | None,
    commands: str,
    password: str,
    debug: bool,
) -> None:
    command = build_ssh_command(host, username, port)
    if debug:
        print(
            f"[debug] Running MikroTik commands via SSH on {username}@{host}",
            file=sys.stderr,
        )
    askpass_path = None
    try:
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            askpass_path = handle.name
            handle.write("#!/bin/sh\n")
            handle.write('printf "%s\\n" "$ROUTER_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)

        env = os.environ.copy()
        env["ROUTER_SSH_PASSWORD"] = password
        env["SSH_ASKPASS"] = askpass_path
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env["DISPLAY"] = env.get("DISPLAY", ":0")

        result = subprocess.run(
            command,
            input=commands,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        if result.returncode != 0:
            if debug:
                if result.stdout:
                    print(
                        f"[debug] SSH stdout: {result.stdout.strip()}",
                        file=sys.stderr,
                    )
                if result.stderr:
                    print(
                        f"[debug] SSH stderr: {result.stderr.strip()}",
                        file=sys.stderr,
                    )
            details = []
            if result.stderr.strip():
                details.append(result.stderr.strip())
            if result.stdout.strip():
                details.append(result.stdout.strip())
            if not details:
                details.append(f"SSH exited with status {result.returncode}")
            raise RuntimeError(" | ".join(details))
    finally:
        if askpass_path:
            try:
                os.remove(askpass_path)
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch NetBox firewall policies and services, then build firewall rules."
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
        "--output",
        default=None,
        help="Output JSON path (default: work_dir/netbox-firewall-policies.json)",
    )
    parser.add_argument(
        "--services-output",
        default=None,
        help="Output JSON path for NetBox services (default: work_dir/netbox-services.json)",
    )
    parser.add_argument(
        "--rules-output",
        default=None,
        help="Output path for generated Mikrotik firewall commands (default: work_dir/netbox-firewall-rules.rsc)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="SSH into the router and apply generated firewall rules",
    )
    parser.add_argument(
        "--router-host",
        default=None,
        help="Router hostname/IP (overrides config)",
    )
    parser.add_argument(
        "--router-username",
        default=None,
        help="Router SSH username (overrides config)",
    )
    parser.add_argument(
        "--router-port",
        default=None,
        help="Router SSH port (overrides config)",
    )
    parser.add_argument(
        "--enabled",
        choices=("true", "false", "all"),
        default="true",
        help="Filter by enabled flag (default: %(default)s)",
    )
    parser.add_argument(
        "--limit",
        default="200",
        help="Page size for NetBox pagination (default: %(default)s)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug output to stderr",
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

    params: dict[str, str] = {"limit": str(args.limit)}
    if args.enabled != "all":
        params["enabled"] = args.enabled

    try:
        records = fetch_all_records(url, headers, params, args.debug)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Unexpected response: {exc}", file=sys.stderr)
        return 1

    output_path = args.output or os.path.join(
        work_dir, "netbox-firewall-policies.json"
    )
    output_payload = {
        "count": len(records),
        "next": None,
        "previous": None,
        "results": records,
    }
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(output_payload, handle, indent=2, sort_keys=True)
    print(f"Saved NetBox firewall policies JSON to {output_path}")

    services_url = build_services_url(base_url, args.debug)
    try:
        services = fetch_all_records(services_url, headers, params, args.debug)
    except requests.RequestException as exc:
        print(f"Services request failed: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Unexpected services response: {exc}", file=sys.stderr)
        return 1

    services_output_path = args.services_output or os.path.join(
        work_dir, "netbox-services.json"
    )
    services_payload = {
        "count": len(services),
        "next": None,
        "previous": None,
        "results": services,
    }
    with open(services_output_path, "w", encoding="utf-8") as handle:
        json.dump(services_payload, handle, indent=2, sort_keys=True)
    print(f"Saved NetBox services JSON to {services_output_path}")

    service_map = build_service_map(services)
    firewall_rules = build_firewall_rules(records, service_map, args.debug)
    rules_output_path = args.rules_output or os.path.join(
        work_dir, "netbox-firewall-rules.rsc"
    )
    router_config = config.get("router", {})
    if not isinstance(router_config, dict):
        router_config = {}
    place_before_comment = router_config.get("place_before_comment", "Drop")
    script_text = (
        "\n".join(render_mikrotik_rules(firewall_rules, place_before_comment)) + "\n"
    )
    with open(rules_output_path, "w", encoding="utf-8") as handle:
        handle.write(script_text)
    print(f"Saved generated firewall rules script to {rules_output_path}")

    if args.apply:
        router_config = config.get("router", {})
        if not isinstance(router_config, dict):
            router_config = {}
        host = args.router_host or router_config.get("host")
        username = args.router_username or router_config.get("username")
        port_value = args.router_port or router_config.get("port")

        port = None
        if port_value is not None:
            try:
                port = int(port_value)
            except (TypeError, ValueError):
                print("Router port must be an integer.", file=sys.stderr)
                return 2

        if not host or not username:
            print(
                "Router host and username are required to apply changes.",
                file=sys.stderr,
            )
            return 2

        try:
            password = getpass.getpass(
                prompt=f"Password for {username}@{host}: "
            )
            run_router_commands(host, username, port, script_text, password, args.debug)
        except RuntimeError as exc:
            print(f"Router update failed: {exc}", file=sys.stderr)
            return 1
        print("Applied firewall rules to router.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
