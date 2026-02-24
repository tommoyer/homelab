#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import get_effective_table, load_toml_or_exit


def load_config(path: Path, debug: bool) -> dict[str, Any]:
    if debug:
        print(f"[debug] Loading config from {path}", file=sys.stderr)
    data = load_toml_or_exit(path)
    if debug:
        print(f"[debug] Loaded config keys: {sorted(data.keys())}", file=sys.stderr)
    return data


def _get_config_value(config: dict[str, Any], key: str, default: Any) -> Any:
    value = config.get(key, default)
    return default if value is None else value


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
        return bool(int(value))
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in {"true", "t", "yes", "y", "1", "on"}:
            return True
        if cleaned in {"false", "f", "no", "n", "0", "off"}:
            return False
    return default


def normalize_ports(value: Any) -> list[int]:
    if is_blank(value) or value is None:
        return []
    if isinstance(value, list):
        ports: list[int] = []
        for item in value:
            ports.extend(normalize_ports(item))
        return ports
    if isinstance(value, (int, float)):
        try:
            return [int(value)]
        except (TypeError, ValueError):
            return []
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return []
        parts = re.split(r"[\s,;/]+", cleaned)
        ports: list[int] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part.isdigit():
                ports.append(int(part))
        return ports
    return []


def normalize_ip(address: str) -> str | None:
    address = (address or "").strip()
    if not address:
        return None
    try:
        return str(ipaddress.ip_interface(address).ip)
    except ValueError:
        try:
            return str(ipaddress.ip_address(address))
        except ValueError:
            return None


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "service"


def caddy_handler_label(fqdn: str) -> str:
    """Return a short, stable label for Caddy matchers/handles.

    The existing working Caddyfile in this repo uses the left-most DNS label
    (e.g. proxmox.moyer.wtf -> proxmox) rather than a full-FQDN slug.
    """

    fqdn = (fqdn or "").strip().lower().rstrip(".")
    if not fqdn:
        return "service"
    leftmost = fqdn.split(".", 1)[0]
    return slugify(leftmost)


def determine_zone(hostname: str, zones: list[str]) -> str | None:
    target = hostname.lower().rstrip(".")
    matches = [zone for zone in zones if target == zone or target.endswith(f".{zone}")]
    if not matches:
        return None
    return max(matches, key=len)


def generate_map_entries(services: list[dict[str, Any]]) -> list[str]:
    if not services:
        return []
    width = max(len(svc["fqdn"]) for svc in services)
    return [
        f"{svc['fqdn'].ljust(width)}  {svc['backend']}"
        for svc in sorted(services, key=lambda item: item["fqdn"].lower())
    ]


def generate_handler_blocks(services: list[dict[str, Any]]) -> list[str]:
    blocks: list[str] = []
    for svc in sorted(services, key=lambda item: item["fqdn"].lower()):
        if not svc.get("ignore_tls"):
            continue
        fqdn = svc["fqdn"]
        backend = svc["backend"]
        label = caddy_handler_label(fqdn)
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
                zones.append({"zone": zone.strip(), "wildcard": True, "redirect_www": False})
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

        if redirect_www:
            header_label = f"Public Web: {zone} (redirect www -> apex)"
        elif wildcard:
            header_label = f"Public Wildcard Handler ({zone})"
        else:
            header_label = f"Public Handler ({zone})"

        block: list[str] = [
            "# ------------------------------------------------------------------",
            f"# {header_label}",
            "# ------------------------------------------------------------------",
            f"{hostnames} {{",
            "    # 1. Cloudflare DNS Challenge for Wildcard Certs",
            "    tls {",
            "        dns cloudflare {env.CLOUDFLARE_API_TOKEN}",
            "    }",
            "",
        ]

        if redirect_www:
            block.extend(
                [
                    f"    @www host www.{zone}",
                    f"    redir @www https://{zone}{{uri}}",
                    "",
                ]
            )

        block.extend(
            [
                "    # 2. Service Map (Hostname -> Backend IP)",
                "    map {host} {backend} {",
                f"        # Generated by generate-caddyfile.py on {generated_at}",
            ]
        )
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

        if handler_blocks:
            block.append(
                "    # 3. Proxied HTTPS backends (Special case: HTTPS backend + Self-Signed)"
            )
            block.extend(indent_lines(handler_blocks, 4))
            block.append("")

        block.extend(
            [
                "    # 4. Generic Handler (Standard HTTP backends)",
                "    @mapped expression {backend} != \"unknown\"",
                "    handle @mapped {",
                "        reverse_proxy {backend}",
                "    }",
                "",
                "    # 5. Fallback for undefined subdomains",
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
    if shutil.which("scp") is None:
        raise RuntimeError("Required command not found in PATH: scp")
    if shutil.which("ssh") is None:
        raise RuntimeError("Required command not found in PATH: ssh")

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


def build_sheet_url(sheet_url: str, gid: int) -> str:
    if "gid=0" not in sheet_url:
        raise ValueError("sheet_url must contain 'gid=0' placeholder")
    return sheet_url.replace("gid=0", f"gid={gid}")


def load_nodes_lookup(nodes_df: pd.DataFrame) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for _, row in nodes_df.iterrows():
        dns_name = as_str(row.get("dns_name"))
        hostname = as_str(row.get("hostname"))
        ip = normalize_ip(as_str(row.get("ip_address")))
        if not ip:
            continue
        if dns_name:
            lookup[dns_name.lower()] = ip
        if hostname:
            lookup[hostname.lower()] = ip
    return lookup


def collect_proxy_services_from_sheet(
    services_df: pd.DataFrame,
    *,
    nodes_lookup: dict[str, str] | None,
    debug: bool,
) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []

    for idx, row in services_df.iterrows():
        enabled = parse_bool(row.get("frontend_enabled"), default=False)
        if not enabled:
            continue

        ingress = as_str(row.get("ingress")).lower()
        if ingress != "caddy":
            continue

        fqdn = as_str(row.get("frontend_hostname"))
        if not fqdn:
            if debug:
                print(
                    f"[debug] Row {idx} missing Frontend Hostname; skipping",
                    file=sys.stderr,
                )
            continue

        protocol = as_str(row.get("protocol"))
        if protocol and protocol.lower() != "tcp":
            if debug:
                print(f"[debug] Row {idx} protocol={protocol}; skipping", file=sys.stderr)
            continue

        ignore_tls = parse_bool(row.get("tls"), default=False)

        backend_ip = normalize_ip(as_str(row.get("ip_address")))

        if not backend_ip and nodes_lookup:
            backend_node = as_str(row.get("hostname"))
            if backend_node:
                backend_ip = nodes_lookup.get(backend_node.lower())

        if not backend_ip:
            if debug:
                print(
                    f"[debug] Row {idx} missing IP Address (and no Nodes match); skipping",
                    file=sys.stderr,
                )
            continue

        ports = normalize_ports(row.get("backend_port"))

        port = ports[0] if ports else None
        if debug and len(ports) > 1:
            print(f"[debug] Row {idx} has multiple ports; using {port}", file=sys.stderr)

        backend = backend_ip if port is None else f"{backend_ip}:{port}"

        services.append(
            {
                "id": int(idx),
                "fqdn": fqdn,
                "backend": backend,
                "ignore_tls": bool(ignore_tls),
            }
        )

    return services


def _ssh_control_path(username: str, host: str) -> Path:
    key = f"{username}@{host}".encode("utf-8")
    digest = hashlib.sha1(key).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"caddy-ssh-{digest}.sock"


def _ssh_mux_options(control_path: Path) -> list[str]:
    return [
        "-o",
        "ControlMaster=auto",
        "-o",
        "ControlPersist=60s",
        "-o",
        f"ControlPath={control_path}",
    ]


def deploy_caddyfile_mux(
    *,
    local_path: str,
    host: str,
    username: str,
    remote_path: str,
    restart_command: str,
    port: int | None,
    debug: bool,
) -> None:
    if shutil.which("scp") is None:
        raise RuntimeError("Required command not found in PATH: scp")
    if shutil.which("ssh") is None:
        raise RuntimeError("Required command not found in PATH: ssh")

    ssh_target = f"{username}@{host}"
    control_path = _ssh_control_path(username, host)
    mux_opts = _ssh_mux_options(control_path)

    # Start (or reuse) a master connection so scp + ssh share auth.
    base_ssh = ["ssh", *mux_opts]
    if port:
        base_ssh.extend(["-p", str(port)])
    subprocess.run([*base_ssh, "-Nf", ssh_target], check=True)

    try:
        scp_cmd = ["scp", *mux_opts]
        if port:
            scp_cmd.extend(["-P", str(port)])
        scp_cmd.extend([local_path, f"{ssh_target}:{remote_path}"])
        if debug:
            print(f"[debug] scp -> {ssh_target}:{remote_path}", file=sys.stderr)
        subprocess.run(scp_cmd, check=True)

        ssh_cmd = ["ssh", *mux_opts]
        if port:
            ssh_cmd.extend(["-p", str(port)])
        ssh_cmd.extend([ssh_target, restart_command])
        if debug:
            print(f"[debug] restart -> {restart_command}", file=sys.stderr)
        subprocess.run(ssh_cmd, check=True)
    finally:
        subprocess.run([*base_ssh, "-O", "exit", ssh_target], check=False)


def main(argv: list[str] | None = None) -> int:
    default_dir = Path(__file__).resolve().parents[1] / "network.old" / "caddy"

    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "--config",
        type=Path,
        default=default_dir / "generate-caddyfile.toml",
        help="Path to TOML config file containing default parameters",
    )
    pre_args, _ = pre_parser.parse_known_args(argv)
    config_path = pre_args.config.expanduser().resolve()
    config = load_config(config_path, debug=False)
    cfg = get_effective_table(config, "caddy", legacy_root_fallback=True)

    parser = argparse.ArgumentParser(
        description=(
            "Generate Caddyfile server blocks from Google Sheets and render Caddyfile.template. "
            "Designed to replace the NetBox-backed update-caddy.py flow."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=config_path,
        help="Path to TOML config file containing default parameters",
    )
    parser.add_argument(
        "--sheet-url",
        default=_get_config_value(cfg, "sheet_url", ""),
        help=(
            "Google Sheets CSV export URL containing 'gid=0'. "
            "The script substitutes Caddy/Nodes gids into this URL."
        ),
    )
    parser.add_argument(
        "--caddy-gid",
        type=int,
        default=_get_config_value(cfg, "caddy_gid", None),
        help="GID for the Caddy/Proxy Services sheet tab",
    )
    parser.add_argument(
        "--nodes-gid",
        type=int,
        default=_get_config_value(cfg, "nodes_gid", None),
        help="Optional: GID for the Nodes sheet tab (for backend_node -> IP lookup)",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(_get_config_value(cfg, "template", str(default_dir / "Caddyfile.template"))),
        help="Path to Caddyfile template (default: Caddyfile.template next to this script)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(_get_config_value(cfg, "output", str(default_dir / "downloads" / "Caddyfile"))),
        help="Output path for generated Caddyfile",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(_get_config_value(cfg, "work_dir", str(default_dir / "downloads"))),
        help="Directory for downloaded/generated files",
    )
    parser.add_argument(
        "--dump-json",
        action="store_true",
        default=bool(_get_config_value(cfg, "dump_json", False)),
        help="If set, save normalized sheet rows to work_dir/caddy-services.json",
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

    args = parser.parse_args(argv)

    config = load_config(args.config.expanduser().resolve(), args.debug)
    cfg = get_effective_table(config, "caddy", legacy_root_fallback=True)

    if not args.sheet_url:
        print("Error: sheet_url is required (set in config or pass --sheet-url).", file=sys.stderr)
        return 2
    if args.caddy_gid is None:
        print("Error: caddy_gid is required (set in config or pass --caddy-gid).", file=sys.stderr)
        return 2

    work_dir = args.work_dir.expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    template_path = args.template.expanduser().resolve()
    if not template_path.exists():
        print(f"Template not found: {template_path}", file=sys.stderr)
        return 2

    template_text = template_path.read_text(encoding="utf-8")

    caddy_url = build_sheet_url(args.sheet_url, int(args.caddy_gid))
    if args.debug:
        print(f"[debug] Loading Caddy sheet CSV: {caddy_url}", file=sys.stderr)

    try:
        services_df = pd.read_csv(caddy_url)
    except Exception as exc:
        print(f"Error: failed to read Caddy sheet CSV: {exc}", file=sys.stderr)
        return 1

    services_df = df_with_normalized_columns(services_df)

    nodes_lookup: dict[str, str] | None = None
    if args.nodes_gid is not None:
        nodes_url = build_sheet_url(args.sheet_url, int(args.nodes_gid))
        if args.debug:
            print(f"[debug] Loading Nodes sheet CSV: {nodes_url}", file=sys.stderr)
        try:
            nodes_df = pd.read_csv(nodes_url)
            nodes_df = df_with_normalized_columns(nodes_df)
            nodes_lookup = load_nodes_lookup(nodes_df)
        except Exception as exc:
            print(f"Error: failed to read Nodes sheet CSV: {exc}", file=sys.stderr)
            return 1

    proxy_services = collect_proxy_services_from_sheet(
        services_df, nodes_lookup=nodes_lookup, debug=args.debug
    )

    if args.dump_json:
        json_path = work_dir / "caddy-services.json"
        json_path.write_text(json.dumps(proxy_services, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Saved normalized services JSON to {json_path}")

    zones_config = normalize_zone_configs(cfg)
    zones = [zone_cfg["zone"] for zone_cfg in zones_config]
    if not zones:
        print(
            "Error: no zones configured. Provide 'caddy_zones' in config.toml.",
            file=sys.stderr,
        )
        return 2

    zone_map_services: dict[str, list[dict[str, Any]]] = {zone: [] for zone in zones}
    zone_handler_services: dict[str, list[dict[str, Any]]] = {zone: [] for zone in zones}

    unmatched: list[str] = []
    for svc in proxy_services:
        zone = determine_zone(svc["fqdn"], zones)
        if not zone:
            unmatched.append(svc["fqdn"])
            continue
        zone_map_services.setdefault(zone, []).append(svc)
        zone_handler_services.setdefault(zone, []).append(svc)

    if unmatched and args.debug:
        for fqdn in unmatched:
            print(f"[debug] No zone match for {fqdn}", file=sys.stderr)

    map_entries_rendered: dict[str, list[str]] = {}
    handler_blocks_rendered: dict[str, list[str]] = {}
    for zone, items in zone_map_services.items():
        map_entries_rendered[zone] = generate_map_entries(items)
    for zone, items in zone_handler_services.items():
        handler_blocks_rendered[zone] = generate_handler_blocks(items)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    server_blocks = generate_server_blocks(
        zones_config,
        map_entries_rendered,
        handler_blocks_rendered,
        generated_at,
    )

    rendered = render_template(template_text, server_blocks)

    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"Saved generated Caddyfile to {output_path}")

    if args.apply:
        deploy_config = cfg.get("caddy_deploy", {})
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
            deploy_caddyfile_mux(
                local_path=str(output_path),
                host=str(host),
                username=str(username),
                remote_path=str(remote_path),
                restart_command=str(restart_command),
                port=port,
                debug=args.debug,
            )
        except Exception as exc:
            print(f"Caddy deploy failed: {exc}", file=sys.stderr)
            return 1
        print("Deployed Caddyfile and restarted Caddy.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
