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
    url = f"{base_url.rstrip('/')}/api/plugins/custom-objects/nat-policies/"
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


def build_nat_rules(
    policies: list[dict[str, Any]],
    service_map: dict[int, dict[str, Any]],
    debug: bool,
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for policy in policies:
        if not policy.get("enabled", False):
            continue

        nat_type = policy.get("nat_type")
        if nat_type not in {"dstnat", "srcnat"}:
            if debug:
                print(
                    f"[debug] Skipping policy {policy.get('id')} with nat_type={nat_type}",
                    file=sys.stderr,
                )
            continue

        in_iface = None
        src_iface_dcim = policy.get("src_iface_dcim")
        if isinstance(src_iface_dcim, dict):
            in_iface = src_iface_dcim.get("name") or src_iface_dcim.get("display")
        src_iface_vm = policy.get("src_iface_vm")
        if not in_iface and isinstance(src_iface_vm, dict):
            in_iface = src_iface_vm.get("name") or src_iface_vm.get("display")

        ext_ports = normalize_ports(policy.get("ext_port"))
        int_ports = normalize_ports(policy.get("int_port"))

        dst_services = policy.get("dst_svc", [])
        if not isinstance(dst_services, list):
            dst_services = []

        if not dst_services and debug:
            print(
                f"[debug] Policy {policy.get('id')} has no dst_svc; skipping",
                file=sys.stderr,
            )

        for dst_service in dst_services:
            if not isinstance(dst_service, dict):
                continue
            service_id = dst_service.get("id")
            service = (
                service_map.get(service_id)
                if isinstance(service_id, int)
                else None
            )
            if service is None:
                if debug:
                    print(
                        f"[debug] Service {service_id} missing for policy {policy.get('id')}",
                        file=sys.stderr,
                    )
                continue

            service_ports = normalize_ports(dst_service.get("ports"))
            dst_ports = ext_ports or service_ports
            to_ports = int_ports or service_ports
            port_pairs: list[tuple[int | None, int | None]] = []
            if dst_ports and to_ports:
                if len(dst_ports) == len(to_ports):
                    port_pairs = list(zip(dst_ports, to_ports, strict=False))
                elif len(to_ports) == 1:
                    port_pairs = [(dst, to_ports[0]) for dst in dst_ports]
                elif len(dst_ports) == 1:
                    port_pairs = [(dst_ports[0], to_port) for to_port in to_ports]
                else:
                    if debug:
                        print(
                            f"[debug] Policy {policy.get('id')} has mismatched ports: "
                            f"dst_ports={dst_ports} to_ports={to_ports}; skipping",
                            file=sys.stderr,
                        )
                    continue
            elif dst_ports:
                port_pairs = [(dst, None) for dst in dst_ports]
            elif to_ports:
                port_pairs = [(None, to_port) for to_port in to_ports]

            protocol = None
            proto_obj = dst_service.get("protocol")
            if isinstance(proto_obj, dict):
                protocol = proto_obj.get("value") or proto_obj.get("label")
            if isinstance(protocol, str):
                protocol = protocol.lower()

            service_ips = extract_ipaddresses(service)
            if not service_ips:
                if debug:
                    print(
                        f"[debug] Service {service_id} has no ipaddresses; skipping",
                        file=sys.stderr,
                    )
                continue

            for service_ip in service_ips:
                for dst_port, to_port in port_pairs or [(None, None)]:
                    rule = {
                        "policy_id": policy.get("id"),
                        "policy_display": policy.get("display"),
                        "comment": policy.get("comment"),
                        "chain": "dstnat" if nat_type == "dstnat" else "srcnat",
                        "action": "dst-nat" if nat_type == "dstnat" else "src-nat",
                        "in_interface": in_iface,
                        "protocol": protocol,
                        "dst_ports": [dst_port] if dst_port is not None else [],
                        "to_address": service_ip,
                        "to_ports": [to_port] if to_port is not None else [],
                        "service_id": service_id,
                        "service_name": dst_service.get("name"),
                    }
                    rules.append(rule)
    return rules


def format_ports(ports: list[int]) -> str | None:
    if not ports:
        return None
    return ",".join(str(port) for port in ports)


def quote_value(value: str) -> str:
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'


def render_mikrotik_rules(rules: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = [
        '/ip firewall nat remove [find comment~"^\\\\[Script\\\\]"]'
    ]
    for rule in rules:
        parts: list[str] = ["add"]
        chain = rule.get("chain")
        if chain:
            parts.append(f"chain={chain}")
        action = rule.get("action")
        if action:
            parts.append(f"action={action}")
        in_iface = rule.get("in_interface")
        if in_iface:
            parts.append(f"in-interface={in_iface}")
        protocol = rule.get("protocol")
        if protocol:
            parts.append(f"protocol={protocol}")
        dst_ports = format_ports(rule.get("dst_ports", []))
        if dst_ports:
            parts.append(f"dst-port={dst_ports}")
        to_address = rule.get("to_address")
        if to_address:
            parts.append(f"to-addresses={to_address}")
        to_ports = format_ports(rule.get("to_ports", []))
        if to_ports:
            parts.append(f"to-ports={to_ports}")

        comment = rule.get("comment")
        if not comment:
            comment = rule.get("policy_display") or rule.get("service_name")
        if comment:
            parts.append(f"comment={quote_value(f'[Script] {comment}')}")

        line = "/ip firewall nat " + " ".join(parts)
        lines.append(line)
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
            if debug and result.stderr:
                print(f"[debug] SSH stderr: {result.stderr.strip()}", file=sys.stderr)
            raise RuntimeError(result.stderr.strip() or "Unknown SSH error")
    finally:
        if askpass_path:
            try:
                os.remove(askpass_path)
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch NetBox NAT policies and services, then build NAT rules."
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
        help="Output JSON path (default: work_dir/netbox-nat-policies.json)",
    )
    parser.add_argument(
        "--services-output",
        default=None,
        help="Output JSON path for NetBox services (default: work_dir/netbox-services.json)",
    )
    parser.add_argument(
        "--rules-output",
        default=None,
        help="Output path for generated Mikrotik NAT commands (default: work_dir/netbox-nat-rules.rsc)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="SSH into the router and apply generated NAT rules",
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

    output_path = args.output or os.path.join(work_dir, "netbox-nat-policies.json")
    output_payload = {
        "count": len(records),
        "next": None,
        "previous": None,
        "results": records,
    }
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(output_payload, handle, indent=2, sort_keys=True)
    print(f"Saved NetBox NAT policies JSON to {output_path}")

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
    nat_rules = build_nat_rules(records, service_map, args.debug)
    rules_output_path = args.rules_output or os.path.join(
        work_dir, "netbox-nat-rules.rsc"
    )
    script_text = "\n".join(render_mikrotik_rules(nat_rules)) + "\n"
    with open(rules_output_path, "w", encoding="utf-8") as handle:
        handle.write(script_text)
    print(f"Saved generated NAT rules script to {rules_output_path}")

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
        print("Applied NAT rules to router.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
