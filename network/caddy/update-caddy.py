#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
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


def build_api_base_url(base_url: str) -> str:
    if "/plugins/custom-objects/" in base_url:
        root = base_url.split("/plugins/custom-objects/")[0]
        return f"{root.rstrip('/')}/api"
    if "/api" in base_url:
        root = base_url.split("/api")[0]
        return f"{root.rstrip('/')}/api"
    if base_url.rstrip("/").endswith("/api"):
        return base_url.rstrip("/")
    return f"{base_url.rstrip('/')}/api"


def build_services_url(base_url: str, debug: bool) -> str:
    api_base = build_api_base_url(base_url)
    url = f"{api_base}/ipam/services/"
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


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "service"


def determine_zone(hostname: str, zones: list[str]) -> str | None:
    target = hostname.lower().rstrip(".")
    matches = [zone for zone in zones if target == zone or target.endswith(f".{zone}")]
    if not matches:
        return None
    return max(matches, key=len)


def collect_proxy_services(
    services: list[dict[str, Any]],
    *,
    debug: bool,
) -> list[dict[str, Any]]:
    proxy_services: list[dict[str, Any]] = []
    for service in services:
        custom_fields = service.get("custom_fields")
        if not isinstance(custom_fields, dict):
            custom_fields = {}
        if not custom_fields.get("behind_proxy"):
            continue

        fqdn = custom_fields.get("proxy_fqdn")
        if not isinstance(fqdn, str) or not fqdn.strip():
            if debug:
                print(
                    f"[debug] Service {service.get('id')} missing proxy_fqdn; skipping",
                    file=sys.stderr,
                )
            continue
        fqdn = fqdn.strip()

        protocol_obj = service.get("protocol")
        if isinstance(protocol_obj, dict):
            proto = protocol_obj.get("value") or protocol_obj.get("label")
        else:
            proto = protocol_obj
        if isinstance(proto, str) and proto.lower() != "tcp":
            if debug:
                print(
                    f"[debug] Service {service.get('id')} protocol={proto}; skipping",
                    file=sys.stderr,
                )
            continue

        ips = extract_ipaddresses(service)
        if not ips:
            if debug:
                print(
                    f"[debug] Service {service.get('id')} has no ipaddresses; skipping",
                    file=sys.stderr,
                )
            continue
        if debug and len(ips) > 1:
            print(
                f"[debug] Service {service.get('id')} has multiple IPs; using {ips[0]}",
                file=sys.stderr,
            )

        ports = normalize_ports(service.get("ports"))
        port = ports[0] if ports else None
        if debug and len(ports) > 1:
            print(
                f"[debug] Service {service.get('id')} has multiple ports; using {port}",
                file=sys.stderr,
            )

        backend = ips[0] if port is None else f"{ips[0]}:{port}"
        proxy_services.append(
            {
                "id": service.get("id"),
                "fqdn": fqdn,
                "backend": backend,
                "ignore_tls": bool(custom_fields.get("proxy_ignore_tls")),
            }
        )

    return proxy_services


def generate_map_entries(services: list[dict[str, Any]]) -> list[str]:
    if not services:
        return []
    width = max(len(svc["fqdn"]) for svc in services)
    lines = [
        f"{svc['fqdn'].ljust(width)}  {svc['backend']}"
        for svc in sorted(services, key=lambda item: item["fqdn"].lower())
    ]
    return lines


def generate_handler_blocks(services: list[dict[str, Any]]) -> list[str]:
    blocks: list[str] = []
    for svc in sorted(services, key=lambda item: item["fqdn"].lower()):
        if not svc.get("ignore_tls"):
            continue
        fqdn = svc["fqdn"]
        backend = svc["backend"]
        label = slugify(fqdn)
        blocks.extend(
            [
                f"@{label} host {fqdn}",
                f"handle @{label} {{",
                f"    reverse_proxy https://{backend} {{",
                "        transport http {",
                "            tls_insecure_skip_verify",
                "        }",
                "    }",
                "}",
                "",
            ]
        )
    if blocks and not blocks[-1].strip():
        blocks.pop()
    return blocks


def replace_block(text: str, token: str, lines: list[str]) -> str:
    pattern = re.compile(rf"^([ \t]*){re.escape(token)}\s*$", re.MULTILINE)

    def repl(match: re.Match[str]) -> str:
        indent = match.group(1)
        if not lines:
            return ""
        return "\n".join(indent + line for line in lines)

    return pattern.sub(repl, text)


def normalize_zone_configs(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw = config.get("caddy_zones")
    if isinstance(raw, list):
        zones: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            zone = item.get("zone")
            if not isinstance(zone, str) or not zone.strip():
                continue
            zones.append(
                {
                    "zone": zone.strip(),
                    "wildcard": bool(item.get("wildcard", True)),
                    "redirect_www": bool(item.get("redirect_www", False)),
                }
            )
        if zones:
            return zones

    filters = config.get("netbox_zone_filters")
    zones = []
    if isinstance(filters, list):
        for item in filters:
            if not isinstance(item, dict):
                continue
            zone = item.get("zone")
            if isinstance(zone, str) and zone.strip():
                zones.append(
                    {"zone": zone.strip(), "wildcard": True, "redirect_www": False}
                )
    return zones


def indent_lines(lines: list[str], spaces: int) -> list[str]:
    prefix = " " * spaces
    return [prefix + line if line else "" for line in lines]


def generate_server_blocks(
    zones: list[dict[str, Any]],
    zone_map_entries: dict[str, list[str]],
    zone_handler_blocks: dict[str, list[str]],
    generated_at: str,
) -> list[str]:
    blocks: list[str] = []
    for zone_cfg in zones:
        zone = zone_cfg["zone"]
        wildcard = zone_cfg.get("wildcard", True)
        redirect_www = zone_cfg.get("redirect_www", False)
        hostnames = f"*.{zone} {zone}" if wildcard else zone

        map_entries = zone_map_entries.get(zone, [])
        handler_blocks = zone_handler_blocks.get(zone, [])

        block: list[str] = [
            f"{hostnames} {{",
            "    # Cloudflare DNS Challenge for Wildcard Certs",
            "    tls {",
            "        dns cloudflare {env.CLOUDFLARE_API_TOKEN}",
            "    }",
            "",
            "    # Service Map (Hostname -> Backend IP)",
            "    map {host} {backend} {",
            f"        # Generated by update-caddy.py on {generated_at}",
        ]
        if map_entries:
            block.extend(indent_lines(map_entries, 8))
        block.extend(
            [
                "",
                "        default                 unknown",
                "    }",
                "",
            ]
        )

        if redirect_www:
            block.extend(
                [
                    f"    @www host www.{zone}",
                    f"    redir @www https://{zone}{{uri}}",
                    "",
                ]
            )

        if handler_blocks:
            block.append("    # Proxied HTTPS backends (self-signed)")
            block.extend(indent_lines(handler_blocks, 4))
            block.append("")

        block.extend(
            [
                "    # Generic Handler (Standard HTTP backends)",
                "    @mapped expression {backend} != \"unknown\"",
                "    handle @mapped {",
                "        reverse_proxy {backend}",
                "    }",
                "",
                "    # Fallback for undefined subdomains",
                "    handle {",
                "        respond \"Service not defined in Caddy Map\" 404",
                "    }",
                "}",
                "",
            ]
        )
        blocks.extend(block)

    if blocks and not blocks[-1].strip():
        blocks.pop()
    return blocks


def render_template(template_text: str, server_blocks: list[str]) -> str:
    rendered = template_text.replace(
        "{{GENERATED_AT}}",
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z"),
    )
    return replace_block(rendered, "{{SERVER_BLOCKS}}", server_blocks)


def build_ssh_command(host: str, username: str, port: int | None) -> list[str]:
    command = ["ssh", "-o", "ConnectTimeout=10"]
    if port:
        command.extend(["-p", str(port)])
    command.append(f"{username}@{host}")
    return command


def build_scp_command(
    local_path: str,
    host: str,
    username: str,
    remote_path: str,
    port: int | None,
) -> list[str]:
    command = ["scp", "-q"]
    if port:
        command.extend(["-P", str(port)])
    command.extend([local_path, f"{username}@{host}:{remote_path}"])
    return command


def deploy_caddyfile(
    *,
    local_path: str,
    host: str,
    username: str,
    remote_path: str,
    restart_command: str,
    port: int | None,
    debug: bool,
) -> None:
    scp_command = build_scp_command(local_path, host, username, remote_path, port)
    if debug:
        print(
            f"[debug] Copying Caddyfile to {username}@{host}:{remote_path}",
            file=sys.stderr,
        )
    result = subprocess.run(scp_command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Caddyfile upload failed")

    ssh_command = build_ssh_command(host, username, port)
    if debug:
        print(
            f"[debug] Restarting Caddy on {username}@{host} with: {restart_command}",
            file=sys.stderr,
        )
    result = subprocess.run(
        ssh_command + [restart_command],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Caddy restart failed")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch NetBox services and generate a Caddyfile."
    )
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "config.toml"),
        help="Path to TOML config (default: %(default)s)",
    )
    parser.add_argument(
        "--template",
        default=os.path.join(os.path.dirname(__file__), "Caddyfile.template"),
        help="Path to Caddyfile template (default: %(default)s)",
    )
    parser.add_argument(
        "--work-dir",
        help="Directory for downloaded/generated files (overrides config)",
    )
    parser.add_argument(
        "--services-output",
        default=None,
        help="Output JSON path for NetBox services (default: work_dir/netbox-services.json)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for generated Caddyfile (default: work_dir/Caddyfile)",
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
        "--apply",
        action="store_true",
        help="Copy generated Caddyfile to server and restart Caddy",
    )
    parser.add_argument(
        "--caddy-host",
        default=None,
        help="Caddy server hostname/IP (overrides config)",
    )
    parser.add_argument(
        "--caddy-username",
        default=None,
        help="Caddy SSH username (overrides config)",
    )
    parser.add_argument(
        "--caddy-port",
        default=None,
        help="Caddy SSH port (overrides config)",
    )
    parser.add_argument(
        "--caddy-path",
        default=None,
        help="Remote Caddyfile path (overrides config)",
    )
    parser.add_argument(
        "--caddy-restart",
        default=None,
        help="Command to restart Caddy on server (overrides config)",
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

    template_path = args.template
    if not os.path.exists(template_path):
        print(f"Template not found: {template_path}", file=sys.stderr)
        return 2

    with open(template_path, "r", encoding="utf-8") as handle:
        template_text = handle.read()

    services_url = build_services_url(base_url, args.debug)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    params: dict[str, str] = {"limit": str(args.limit)}
    if args.enabled != "all":
        params["enabled"] = args.enabled

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

    proxy_services = collect_proxy_services(services, debug=args.debug)
    zones_config = normalize_zone_configs(config)
    zones = [zone_cfg["zone"] for zone_cfg in zones_config]
    zone_map_entries: dict[str, list[str]] = {zone: [] for zone in zones}
    zone_handler_blocks: dict[str, list[str]] = {zone: [] for zone in zones}

    unmatched: list[str] = []
    for svc in proxy_services:
        zone = determine_zone(svc["fqdn"], zones)
        if not zone:
            unmatched.append(svc["fqdn"])
            continue
        zone_map_entries.setdefault(zone, []).append(svc)
        zone_handler_blocks.setdefault(zone, []).append(svc)

    if unmatched and args.debug:
        for fqdn in unmatched:
            print(f"[debug] No zone match for {fqdn}", file=sys.stderr)

    map_entries_rendered: dict[str, list[str]] = {}
    handler_blocks_rendered: dict[str, list[str]] = {}
    for zone, items in zone_map_entries.items():
        map_entries_rendered[zone] = generate_map_entries(items)
    for zone, items in zone_handler_blocks.items():
        handler_blocks_rendered[zone] = generate_handler_blocks(items)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    server_blocks = generate_server_blocks(
        zones_config,
        map_entries_rendered,
        handler_blocks_rendered,
        generated_at,
    )

    rendered = render_template(template_text, server_blocks)

    output_path = args.output or os.path.join(work_dir, "Caddyfile")
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    print(f"Saved generated Caddyfile to {output_path}")

    if args.apply:
        deploy_config = config.get("caddy_deploy", {})
        if not isinstance(deploy_config, dict):
            deploy_config = {}
        host = args.caddy_host or deploy_config.get("host")
        username = args.caddy_username or deploy_config.get("username")
        remote_path = args.caddy_path or deploy_config.get("path")
        restart_command = args.caddy_restart or deploy_config.get("restart_command")
        port_value = args.caddy_port or deploy_config.get("port")

        port = None
        if port_value is not None:
            try:
                port = int(port_value)
            except (TypeError, ValueError):
                print("Caddy port must be an integer.", file=sys.stderr)
                return 2

        if not host or not username or not remote_path or not restart_command:
            print(
                "Caddy deploy settings (host, username, path, restart_command) are required.",
                file=sys.stderr,
            )
            return 2

        try:
            deploy_caddyfile(
                local_path=output_path,
                host=host,
                username=username,
                remote_path=remote_path,
                restart_command=restart_command,
                port=port,
                debug=args.debug,
            )
        except RuntimeError as exc:
            print(f"Caddy deploy failed: {exc}", file=sys.stderr)
            return 1
        print("Deployed Caddyfile and restarted Caddy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
