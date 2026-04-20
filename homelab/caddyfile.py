#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pandas as pd

from .config import (
    get_config_value,
    get_effective_table,
    load_toml_or_exit,
    pre_parse_config,
    render_jinja_template,
    resolve_path_relative_to_config,
)
from .logging_utils import configure_logging
from .resolver import build_resolver
from .sheets import (
    as_str,
    build_sheet_url,
    get_sheet_df,
    load_nodes_lookup,
    normalize_ip,
    normalize_ports,
    parse_bool,
)
from .ssh import (
    require_command,
    scp_base_args,
    ssh_base_args,
    ssh_control_path,
    ssh_run,
    ssh_start_master,
    ssh_stop_master,
)

logger = logging.getLogger(__name__)


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


def caddy_hostname_label(fqdn: str) -> str:
    fqdn = (fqdn or "").strip().lower().rstrip(".")
    if not fqdn:
        return "service"
    return slugify(fqdn.split(".", 1)[0])


def split_fqdn_list(value: Any, *, debug: bool = False) -> list[tuple[str, int | None]]:
    raw = as_str(value)
    if not raw:
        return []
    values: list[tuple[str, int | None]] = []
    for item in raw.split(";"):
        token = item.strip()
        if not token:
            continue

        fqdn_part = token
        port_override: int | None = None
        if ":" in token:
            fqdn_part, port_part = token.rsplit(":", 1)
            port_part = port_part.strip()
            if port_part:
                try:
                    parsed_port = int(port_part)
                    if 1 <= parsed_port <= 65535:
                        port_override = parsed_port
                    else:
                        if debug:
                            print(
                                f"[debug] Ignoring invalid extra_cname port {port_part!r} in {token!r}",
                                file=sys.stderr,
                            )
                except ValueError:
                    if debug:
                        print(
                            f"[debug] Ignoring non-integer extra_cname port {port_part!r} in {token!r}",
                            file=sys.stderr,
                        )

        fqdn = fqdn_part.strip().lower().rstrip(".")
        if fqdn:
            values.append((fqdn, port_override))
    return values


def normalize_exposure(value: Any) -> str:
    exposure = as_str(value).strip().lower().replace("_", "-")
    if exposure in {"trusted", "tailnet-only", "non-public"}:
        return "trusted"
    return exposure or "public"


def trusted_frontend_hostname(frontend_hostname: str, tailnet_domain: str) -> str | None:
    host = (frontend_hostname or "").strip().lower().rstrip(".")
    tailnet = (tailnet_domain or "").strip().lower().rstrip(".")
    if not host or not tailnet:
        return None
    leftmost = host.split(".", 1)[0].strip()
    if not leftmost:
        return None
    return f"{leftmost}.{tailnet}"


def is_fqdn_in_zone(fqdn: str, zone: str) -> bool:
    host = (fqdn or "").strip().lower().rstrip(".")
    target_zone = (zone or "").strip().lower().rstrip(".")
    if not host or not target_zone:
        return False
    return host == target_zone or host.endswith(f".{target_zone}")


def resolve_host_template_path(*, template_dir: Path | None, fqdn: str) -> Path | None:
    if template_dir is None:
        return None
    host = caddy_hostname_label(fqdn)
    normalized_fqdn = (fqdn or "").strip().lower().rstrip(".")
    candidates = [
        template_dir / f"{normalized_fqdn}.j2",
        template_dir / f"{host}.j2",
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def render_host_template_block_lines(
    *,
    template_dir: Path | None,
    svc: dict[str, Any],
    debug: bool,
) -> list[str]:
    fqdn = str(svc["fqdn"])
    backend = str(svc["backend"])
    host = caddy_hostname_label(fqdn)
    template_path = resolve_host_template_path(template_dir=template_dir, fqdn=fqdn)

    if template_path is None:
        return []

    try:
        rendered = render_jinja_template(
            template_path=template_path,
            context={
                "fqdn": fqdn,
                "backend": backend,
                "hostname": host,
                "service": svc,
                "handler_label": f"svc-{caddy_handler_label(fqdn)}",
            },
        )
    except Exception as exc:
        print(
            f"Error: failed to render host template '{template_path.name}' for {fqdn}: {exc}",
            file=sys.stderr,
        )
        raise

    lines = [line.rstrip() for line in rendered.splitlines()]
    while lines and not lines[-1]:
        lines.pop()

    if not lines:
        print(
            f"Error: host template '{template_path.name}' rendered empty for {fqdn}",
            file=sys.stderr,
        )
        raise ValueError(f"empty host template: {template_path}")

    if debug:
        logger.debug("caddy: host template for %s -> %s", fqdn, template_path.name)
    return lines


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


def generate_handler_blocks(
    services: list[dict[str, Any]],
    *,
    template_dir: Path | None,
    debug: bool,
) -> list[str]:
    blocks: list[str] = []
    for svc in sorted(services, key=lambda item: item["fqdn"].lower()):
        template_lines = render_host_template_block_lines(
            template_dir=template_dir,
            svc=svc,
            debug=debug,
        )
        if not template_lines:
            continue
        blocks.extend(template_lines)
        if blocks and blocks[-1].strip():
            blocks.append("")
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
            tls_mode = str(item.get("tls_mode", "cloudflare")).strip().lower()
            if tls_mode not in ("cloudflare", "tailscale"):
                tls_mode = "cloudflare"
            zones.append(
                {
                    "zone": zone.strip(),
                    "wildcard": bool(item.get("wildcard", True)),
                    "redirect_www": bool(item.get("redirect_www", False)),
                    "tls_mode": tls_mode,
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
                    {"zone": zone.strip(), "wildcard": True, "redirect_www": False, "tls_mode": "cloudflare"}
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
        tls_mode = zone_cfg.get("tls_mode", "cloudflare")
        hostnames = f"*.{zone} {zone}" if wildcard else zone

        map_entries = zone_map_entries.get(zone, [])
        handler_blocks = zone_handler_blocks.get(zone, [])

        if tls_mode == "tailscale":
            header_label = f"Tailnet Handler ({zone})"
        elif redirect_www:
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
        ]

        if tls_mode == "tailscale":
            block.extend(
                [
                    "    # 1. Tailscale Certificate Provisioning",
                    "    tls {",
                    "        get_certificate tailscale",
                    "    }",
                    "",
                ]
            )
        else:
            block.extend(
                [
                    "    # 1. Cloudflare DNS Challenge for Wildcard Certs",
                    "    tls {",
                    "        dns cloudflare {env.CLOUDFLARE_API_TOKEN}",
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
            block.append("    # 3. Custom host handlers (template-driven)")
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


def collect_proxy_services_from_sheet(
    services_df: pd.DataFrame,
    *,
    nodes_lookup: dict[str, str] | None,
    trusted_zone: str | None,
    debug: bool,
) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []

    for idx, row in services_df.iterrows():
        row_id = int(cast(int, idx))
        ingress = as_str(row.get("ingress")).lower()
        if ingress != "caddy":
            continue

        frontend_hostname = as_str(row.get("frontend_hostname"))
        if not frontend_hostname:
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

        exposure = normalize_exposure(row.get("exposure"))
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

        default_port = ports[0] if ports else None
        if debug and len(ports) > 1:
            print(f"[debug] Row {idx} has multiple ports; using {default_port}", file=sys.stderr)

        aliases: list[tuple[str, int | None]] = []
        if exposure == "trusted":
            trusted_primary = trusted_frontend_hostname(frontend_hostname, trusted_zone or "")
            if not trusted_primary:
                raise ValueError(
                    f"Row {idx} exposure=trusted requires a trusted/private zone and a valid Frontend Hostname"
                )
            aliases.append((trusted_primary, None))
            for alias, port_override in split_fqdn_list(row.get("extra_cnames"), debug=debug):
                if is_fqdn_in_zone(alias, trusted_zone or ""):
                    aliases.append((alias, port_override))
                else:
                    raise ValueError(
                        f"Row {idx} trusted alias {alias!r} must be in trusted/private zone {trusted_zone!r}"
                    )
        else:
            aliases.append((frontend_hostname, None))
            aliases.extend(split_fqdn_list(row.get("extra_cnames"), debug=debug))

        for fqdn, port_override in dict.fromkeys(aliases):
            effective_port = port_override if port_override is not None else default_port
            backend = backend_ip if effective_port is None else f"{backend_ip}:{effective_port}"
            services.append(
                {
                    "id": row_id,
                    "fqdn": fqdn,
                    "backend": backend,
                    "ignore_tls": bool(ignore_tls),
                    "exposure": exposure,
                }
            )

    return services


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
    require_command("scp")
    require_command("ssh")

    target = f"{username}@{host}"
    effective_port = port or 22
    control_path = ssh_control_path(prefix="caddy", username=username, host=host, port=effective_port)

    ssh_args = ssh_base_args(control_path=control_path, port=effective_port, identity_file=None)
    scp_args_list = scp_base_args(control_path=control_path, port=effective_port, identity_file=None)

    ssh_start_master(ssh_args=ssh_args, target=target, env=None)
    try:
        logger.debug("caddy: scp -> %s:%s", target, remote_path)
        subprocess.run([*scp_args_list, local_path, f"{target}:{remote_path}"], check=True)

        logger.debug("caddy: restart -> %s", restart_command)
        ssh_run(ssh_args=ssh_args, target=target, command=restart_command, env=None)
    finally:
        ssh_stop_master(ssh_args=ssh_args, target=target, env=None)


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    default_template_dir = repo_root / "templates" / "caddy"
    default_output_dir = repo_root / "generated" / "caddy"
    config_path, config = pre_parse_config(argv)
    globals_cfg = get_effective_table(config, "globals", legacy_root_fallback=True)
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
        default=get_config_value(globals_cfg, "sheet_url", get_config_value(cfg, "sheet_url", "")),
        help=(
            "Google Sheets CSV export URL containing 'gid=0'. "
            "The script substitutes Caddy/Nodes gids into this URL."
        ),
    )
    parser.add_argument(
        "--caddy-gid",
        type=int,
        default=get_config_value(
            globals_cfg,
            "services_gid",
            get_config_value(globals_cfg, "caddy_gid", get_config_value(cfg, "caddy_gid", None)),
        ),
        help="GID for the Caddy/Proxy Services sheet tab",
    )
    parser.add_argument(
        "--nodes-gid",
        type=int,
        default=get_config_value(globals_cfg, "nodes_gid", get_config_value(cfg, "nodes_gid", None)),
        help="Optional: GID for the Nodes sheet tab (for backend_node -> IP lookup)",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(get_config_value(cfg, "template", str(default_template_dir / "Caddyfile.j2"))),
        help="Path to Caddyfile template (default: templates/caddy/Caddyfile.j2)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(get_config_value(cfg, "output", str(default_output_dir / "Caddyfile"))),
        help="Output path for generated Caddyfile",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(get_config_value(cfg, "work_dir", str(default_output_dir / "downloads"))),
        help="Directory for downloaded/generated files",
    )
    parser.add_argument(
        "--dump-json",
        action="store_true",
        default=bool(get_config_value(cfg, "dump_json", False)),
        help="If set, save normalized sheet rows to work_dir/caddy-services.json",
    )

    parser.add_argument(
        "--caddy-ip",
        dest="caddy_ip",
        default=get_config_value(
            globals_cfg,
            "caddy_host",
            get_config_value(
                globals_cfg,
                "caddy_ip",
                get_config_value(cfg, "health_check_ip", "127.0.0.1"),
            ),
        ),
        help=(
            "Caddy proxy IP/hostname in the DMZ VLAN (used by the template for the health check listener). "
            "Defaults to [globals].caddy_host; override via this flag."
        ),
    )

    # Backward-compatible alias for older configs/flags.
    parser.add_argument(
        "--health-check-ip",
        dest="caddy_ip",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--_apply",
        dest="apply",
        action="store_true",
        help=argparse.SUPPRESS,
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
        "--_debug",
        dest="debug",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args(argv)

    if args.debug:
        configure_logging(debug=True)
        logger.debug("caddy: debug enabled")

    config_path = args.config.expanduser().resolve()
    config = load_toml_or_exit(config_path)
    cfg = get_effective_table(config, "caddy", legacy_root_fallback=True)
    globals_cfg = get_effective_table(config, "globals", legacy_root_fallback=True)
    tailscale_cfg = get_effective_table(config, "tailscale", legacy_root_fallback=True)
    tailnet_domain = as_str(get_config_value(tailscale_cfg, "tailnet_domain", "")).strip().lower().rstrip(".")
    trusted_zone = as_str(get_config_value(globals_cfg, "trusted_zone", "")).strip().lower().rstrip(".")

    if not args.sheet_url:
        print("Error: sheet_url is required (set in config or pass --sheet-url).", file=sys.stderr)
        return 2
    if args.caddy_gid is None:
        print("Error: caddy_gid is required (set in config or pass --caddy-gid).", file=sys.stderr)
        return 2

    work_dir = resolve_path_relative_to_config(config_path, args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    template_path = resolve_path_relative_to_config(config_path, args.template)
    if not template_path.exists():
        print(f"Template not found: {template_path}", file=sys.stderr)
        return 2

    caddy_url = build_sheet_url(args.sheet_url, int(args.caddy_gid))
    if args.debug:
        logger.debug("caddy: loading Services sheet CSV: %s", caddy_url)

    services_df = get_sheet_df(args.sheet_url, int(args.caddy_gid), 30.0, "Caddy Services")

    nodes_lookup: dict[str, str] | None = None
    if args.nodes_gid is not None:
        nodes_url = build_sheet_url(args.sheet_url, int(args.nodes_gid))
        if args.debug:
            logger.debug("caddy: loading Nodes sheet CSV: %s", nodes_url)
        try:
            nodes_df = get_sheet_df(args.sheet_url, int(args.nodes_gid), 30.0, "Nodes")
            nodes_lookup = load_nodes_lookup(nodes_df)
        except Exception as exc:
            print(f"Error: failed to read Nodes sheet CSV: {exc}", file=sys.stderr)
            return 1

    proxy_services = collect_proxy_services_from_sheet(
        services_df,
        nodes_lookup=nodes_lookup,
        trusted_zone=trusted_zone,
        debug=args.debug,
    )

    if args.dump_json:
        json_path = work_dir / "caddy-services.json"
        json_path.write_text(json.dumps(proxy_services, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Saved normalized services JSON to {json_path}")

    zones_config = normalize_zone_configs(cfg)
    if not zones_config:
        print(
            "Error: no zones configured. Provide 'caddy_zones' in config.toml.",
            file=sys.stderr,
        )
        return 2

    trusted_zone_cfgs = [
        zone_cfg
        for zone_cfg in zones_config
        if zone_cfg.get("zone", "").strip().lower().rstrip(".") == trusted_zone
    ]

    has_trusted_services = any(svc.get("exposure") == "trusted" for svc in proxy_services)
    trusted_zone_name = trusted_zone_cfgs[0]["zone"] if trusted_zone_cfgs else ""
    public_zones_cfg = [zone_cfg for zone_cfg in zones_config if zone_cfg.get("zone") != trusted_zone_name]
    trusted_zones = [trusted_zone_name] if trusted_zone_name else []
    public_zones = [zone_cfg["zone"] for zone_cfg in public_zones_cfg]
    has_public_services = any(svc.get("exposure") != "trusted" for svc in proxy_services)

    if has_trusted_services and not trusted_zone:
        print(
            "Error: trusted/private zone is required when Services rows use exposure=trusted "
            "(set [globals].trusted_zone).",
            file=sys.stderr,
        )
        return 2

    if has_trusted_services and len(trusted_zone_cfgs) != 1:
        print(
            "Error: exactly one caddy_zones entry must match the trusted/private zone "
            "when exposure=trusted services exist.",
            file=sys.stderr,
        )
        return 2

    if has_trusted_services and tailnet_domain and is_fqdn_in_zone(tailnet_domain, trusted_zone):
        print(
            "Error: trusted/private zone must be distinct from [tailscale].tailnet_domain "
            "for hard-cutover naming.",
            file=sys.stderr,
        )
        return 2

    if has_trusted_services:
        trusted_mode = str(trusted_zone_cfgs[0].get("tls_mode", "cloudflare")).strip().lower()
        if trusted_mode == "tailscale":
            print(
                "Error: trusted/private zone cannot use tls_mode='tailscale'. "
                "Use a non-tailnet private zone for trusted services.",
                file=sys.stderr,
            )
            return 2

    if has_public_services and not public_zones:
        print(
            "Error: at least one non-tailscale caddy_zones entry is required for non-trusted services.",
            file=sys.stderr,
        )
        return 2

    all_zones = [zone_cfg["zone"] for zone_cfg in zones_config]
    zone_map_services: dict[str, list[dict[str, Any]]] = {zone: [] for zone in all_zones}
    zone_handler_services: dict[str, list[dict[str, Any]]] = {zone: [] for zone in all_zones}
    host_template_dir = template_path.parent

    unmatched: list[str] = []
    for svc in proxy_services:
        exposure = svc.get("exposure")
        candidate_zones = trusted_zones if exposure == "trusted" else public_zones
        zone = determine_zone(svc["fqdn"], candidate_zones)
        if not zone:
            unmatched.append(svc["fqdn"])
            continue
        if resolve_host_template_path(template_dir=host_template_dir, fqdn=svc["fqdn"]):
            zone_handler_services.setdefault(zone, []).append(svc)
        else:
            zone_map_services.setdefault(zone, []).append(svc)

    if unmatched and args.debug:
        for fqdn in unmatched:
            logger.debug("caddy: no zone match for %s", fqdn)

    map_entries_rendered: dict[str, list[str]] = {}
    handler_blocks_rendered: dict[str, list[str]] = {}
    for zone, items in zone_map_services.items():
        map_entries_rendered[zone] = generate_map_entries(items)
    for zone, items in zone_handler_services.items():
        handler_blocks_rendered[zone] = generate_handler_blocks(
            items,
            template_dir=host_template_dir,
            debug=args.debug,
        )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    server_blocks = generate_server_blocks(
        zones_config,
        map_entries_rendered,
        handler_blocks_rendered,
        generated_at,
    )

    if not str(args.caddy_ip).strip():
        print(
            "Error: caddy_ip is required (set in config or pass --caddy-ip).",
            file=sys.stderr,
        )
        return 2

    rendered = render_jinja_template(
        template_path=template_path,
        context={
            "generated_at": generated_at,
            "server_blocks_text": "\n".join(server_blocks).rstrip(),
            "caddy_ip": str(args.caddy_ip).strip(),
        },
    )

    output_path = resolve_path_relative_to_config(config_path, args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"Saved generated Caddyfile to {output_path}")

    deploy_config = cfg.get("caddy_deploy", {})
    if not isinstance(deploy_config, dict):
        deploy_config = {}

    host = args.caddy_host or deploy_config.get("host")
    # Fall back to globals.caddy_host for deploy target when not explicitly set.
    if not host:
        host = str(args.caddy_ip).strip() or None
    username = args.caddy_username or deploy_config.get("username")
    remote_path = args.caddy_path or deploy_config.get("path")
    restart_command = args.caddy_restart or deploy_config.get("restart_command")
    port_value = args.caddy_port or deploy_config.get("port")

    # Resolve the deploy host through Tailscale if it is a hostname.
    if host:
        resolver = build_resolver(config)
        host = resolver.resolve(str(host))

    port = None
    if port_value is not None:
        try:
            port = int(port_value)
        except (TypeError, ValueError):
            print("Caddy port must be an integer.", file=sys.stderr)
            return 2

    missing_deploy: list[str] = []
    if not host:
        missing_deploy.append("host")
    if not username:
        missing_deploy.append("username")
    if not remote_path:
        missing_deploy.append("path")
    if not restart_command:
        missing_deploy.append("restart_command")

    if args.apply:
        if missing_deploy:
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
    else:
        print("Dry run (apply mode disabled): no remote changes made")
        print(f"- generated: {output_path}")
        if missing_deploy:
            print(
                "- would apply: skipped (missing deploy settings: " + ", ".join(missing_deploy) + ")"
            )
            print(
                "- hint: set [caddy].caddy_deploy.{host,username,path,restart_command} in config.toml "
                "or pass --caddy-host/--caddy-username/--caddy-path/--caddy-restart"
            )
        else:
            target = f"{username}@{host}"
            effective_port = port or 22
            print(f"- would scp: {output_path} -> {target}:{remote_path} (port {effective_port})")
            print(f"- would ssh: {target}: {restart_command}")
        print("Re-run with global --apply to perform these actions.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
