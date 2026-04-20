from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import (
    DEFAULT_SHEET_URL,
    get_config_value,
    get_effective_table,
    load_toml_or_exit,
    pre_parse_config,
    render_jinja_template,
    resolve_path_relative_to_config,
)
from .resolver import build_resolver
from .sheets import (
    as_str,
    build_sheet_url,
    df_with_normalized_columns,
    get_sheet_df,
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

_ALLOWED_EXPOSURES = {"public", "private", "local"}


def _normalize_name(value: Any) -> str:
    return as_str(value).lower().rstrip(".")


def _normalize_exposure_strict(value: Any, *, row_hint: str) -> str:
    exposure = as_str(value).lower().strip().replace("_", "-")
    if not exposure:
        raise RuntimeError(
            f"Services row {row_hint}: exposure is required and must be one of public/private/local"
        )
    if exposure not in _ALLOWED_EXPOSURES:
        raise RuntimeError(
            f"Services row {row_hint}: unsupported exposure {exposure!r}; use only public/private/local"
        )
    return exposure


def _sheet_row_hint(index: object) -> str:
    try:
        return str(int(str(index)) + 2)
    except Exception:
        return str(index)


# ---------------------------
# Public DNS (Cloudflare)
# ---------------------------


def _determine_zone(hostname: str, zones: list[str]) -> str | None:
    target = _normalize_name(hostname)
    matches = [zone for zone in zones if target == zone or target.endswith(f".{zone}")]
    if not matches:
        return None
    return max(matches, key=len)


def _to_record_name(*, fqdn: str, zone: str) -> str:
    if fqdn == zone:
        return "@"
    suffix = f".{zone}"
    if not fqdn.endswith(suffix):
        raise ValueError(f"hostname {fqdn!r} is not part of zone {zone!r}")
    relative = fqdn[: -len(suffix)]
    return relative or "@"


def _load_zone_list(*, dns_cfg: dict[str, Any], caddy_cfg: dict[str, Any]) -> list[str]:
    zones: list[str] = []

    raw_dns_zones = dns_cfg.get("zones")
    if isinstance(raw_dns_zones, list):
        for item in raw_dns_zones:
            if isinstance(item, str):
                zone = _normalize_name(item)
                if zone:
                    zones.append(zone)

    raw_caddy_zones = caddy_cfg.get("caddy_zones")
    if isinstance(raw_caddy_zones, list):
        for item in raw_caddy_zones:
            if not isinstance(item, dict):
                continue
            zone = _normalize_name(item.get("zone"))
            if zone:
                zones.append(zone)

    return sorted(set(zones), key=str.lower)


def _load_external_zones_from_sheet(*, sheet_url: str, zones_gid: int, debug: bool = False) -> list[str]:
    zones_df = get_sheet_df(sheet_url, int(zones_gid), 30.0, "Zones")
    zones_df = df_with_normalized_columns(zones_df)

    external_zones: list[str] = []
    for idx, row in zones_df.iterrows():
        dns_zone = _normalize_name(row.get("dns_zone"))
        dns_views = as_str(row.get("dns_views")).lower()
        if not dns_zone:
            continue
        views = [v.strip() for v in dns_views.split(",")]
        if "external" in views:
            external_zones.append(dns_zone)
            if debug:
                print(
                    f"[dns debug] row {idx}: zone {dns_zone!r} has external DNS view",
                    file=sys.stderr,
                )
        elif debug:
            print(
                f"[dns debug] row {idx}: zone {dns_zone!r} skipped (views={views!r})",
                file=sys.stderr,
            )

    return sorted(set(external_zones), key=str.lower)


def _collect_public_records(*, services_df: pd.DataFrame, zones: list[str], debug: bool) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen_by_fqdn: dict[str, dict[str, str]] = {}

    for idx, row in services_df.iterrows():
        row_hint = _sheet_row_hint(idx)
        exposure = _normalize_exposure_strict(row.get("exposure"), row_hint=row_hint)
        if exposure != "public":
            continue

        ingress = _normalize_name(row.get("ingress"))
        if ingress not in {"caddy", "direct"}:
            if debug:
                print(
                    f"[dns debug] row {idx}: unsupported ingress={ingress!r} for public service; skipping",
                    file=sys.stderr,
                )
            continue

        fqdn = _normalize_name(row.get("frontend_hostname"))
        if not fqdn:
            if debug:
                print(f"[dns debug] row {idx}: missing frontend_hostname; skipping", file=sys.stderr)
            continue

        zone = _determine_zone(fqdn, zones)
        if not zone:
            raise RuntimeError(
                f"service row {row_hint} hostname {fqdn!r} does not match any configured dns zone"
            )

        name = _to_record_name(fqdn=fqdn, zone=zone)
        record = {
            "fqdn": fqdn,
            "zone": zone,
            "name": name,
            "ingress": ingress,
        }

        existing = seen_by_fqdn.get(fqdn)
        if existing and existing["ingress"] != ingress:
            raise RuntimeError(
                f"conflicting public records for {fqdn!r}: ingress {existing['ingress']!r} and {ingress!r}"
            )
        if existing:
            if debug:
                print(
                    f"[dns debug] row {idx}: duplicate public service for {fqdn}; keeping first",
                    file=sys.stderr,
                )
            continue

        seen_by_fqdn[fqdn] = record
        records.append(record)

    return sorted(records, key=lambda item: item["fqdn"])


def _render_dnsconfig(*, zones: list[str], public_ip: str, records: list[dict[str, str]]) -> str:
    grouped: dict[str, list[dict[str, str]]] = {zone: [] for zone in zones}
    for record in records:
        grouped.setdefault(record["zone"], []).append(record)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    lines: list[str] = [
        "// AUTOGENERATED by homelab dns generator.",
        f"// Generated at {generated_at}",
        "",
        'var REG_NONE = NewRegistrar("none");',
        'var DSP_CLOUDFLARE = NewDnsProvider("cloudflare");',
        "",
        '// Meta settings for individual records.',
        'var CF_PROXY_OFF = {"cloudflare_proxy": "off"};     // Proxy disabled.',
        'var CF_PROXY_ON = {"cloudflare_proxy": "on"};       // Proxy enabled.',
        "",
    ]

    for zone in zones:
        zone_records = sorted(grouped.get(zone, []), key=lambda item: item["fqdn"])
        zone_fqdn = f"{zone}."

        apex_proxy = any(r["name"] == "@" and r["ingress"] == "caddy" for r in zone_records)

        lines.append(f'D("{zone}", REG_NONE, DnsProvider(DSP_CLOUDFLARE),')
        if apex_proxy:
            apex_meta = json.dumps({"cloudflare_proxy": "on"}, separators=(",", ": "))
            lines.append(f'  A("@", "{public_ip}", {apex_meta}),')
        else:
            lines.append(f'  A("@", "{public_ip}"),')

        for record in zone_records:
            if record["name"] == "@":
                continue
            proxy_value = "CF_PROXY_ON" if record["ingress"] == "caddy" else "CF_PROXY_OFF"
            lines.append(f'  CNAME("{record["name"]}", "{zone_fqdn}", {proxy_value}),')

        lines.append(");")
        lines.append("")

    if lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def _render_creds_json(*, apitoken: str | None, accountid: str | None) -> str:
    payload = {
        "cloudflare": {
            "TYPE": "CLOUDFLAREAPI",
            "apitoken": apitoken or "REPLACE_WITH_CLOUDFLARE_API_TOKEN",
            "accountid": accountid or "REPLACE_WITH_CLOUDFLARE_ACCOUNT_ID",
        }
    }
    return json.dumps(payload, indent=2) + "\n"


# ---------------------------
# Internal DNS (Pi-hole)
# ---------------------------


def _toml_escape_string(value: str) -> str:
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    value = value.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{value}"'


def _toml_string_array(values: list[str]) -> str:
    if not values:
        return "[]"
    lines = ["["]
    for value in values:
        lines.append(f"  {_toml_escape_string(value)},")
    lines.append("]")
    return "\n".join(lines)


def _first_hostname_label(value: object) -> str:
    return as_str(value).lower().strip().rstrip(".").split(".")[0]


def _split_fqdn_list(value: object) -> list[str]:
    raw = as_str(value)
    if not raw:
        return []
    values: list[str] = []
    for item in raw.split(";"):
        fqdn = item.strip().split(":", 1)[0].lower().rstrip(".")
        if fqdn:
            values.append(fqdn)
    return values


def _render_internal_config(
    *,
    sheet_url: str,
    nodes_gid: int,
    services_gid: int,
    template_path: Path,
    caddy_host: str,
    tailnet_domain: str,
    exposures: set[str],
    trace_hostname: str | None = None,
    debug: bool = False,
) -> str:
    if not template_path.exists():
        raise RuntimeError(f"template not found: {template_path}")

    nodes_url = build_sheet_url(sheet_url, int(nodes_gid))
    services_url = build_sheet_url(sheet_url, int(services_gid))
    logger.debug("dns: nodes_url=%s", nodes_url)
    logger.debug("dns: services_url=%s", services_url)

    try:
        nodes_df = get_sheet_df(sheet_url, int(nodes_gid), 30.0, "Nodes")
        services_df = get_sheet_df(sheet_url, int(services_gid), 30.0, "Services")
    except Exception as exc:
        raise RuntimeError(f"error loading sheets: {exc}") from exc

    nodes_df = df_with_normalized_columns(nodes_df)
    services_df = df_with_normalized_columns(services_df)

    trace_key = as_str(trace_hostname).lower().rstrip(".")

    def _norm_hostname(value: object) -> str:
        return as_str(value).lower().rstrip(".")

    def _should_trace(*values: object) -> bool:
        if debug:
            return True
        if not trace_key:
            return False
        return any(_norm_hostname(value) == trace_key for value in values)

    def _trace(message: str, *values: object) -> None:
        if not _should_trace(*values):
            return
        scope = trace_key or "all"
        print(f"[dns trace:{scope}] {message}", file=sys.stderr)

    a_records: list[str] = []
    nodes_cname_by_alias: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for node_idx, row in nodes_df.iterrows():
        dns_name = as_str(row.get("dns_name")).lower().rstrip(".")
        hostname = as_str(row.get("hostname")).lower().rstrip(".")
        ip = as_str(row.get("ip_address"))
        row_hint = _sheet_row_hint(node_idx)

        host_for_a = dns_name or hostname
        if ip and host_for_a:
            a_records.append(f"{ip} {host_for_a}")
            _trace(f"Nodes row {row_hint}: add A record {ip} {host_for_a}", hostname, dns_name, host_for_a)

        disable_cname = parse_bool(row.get("disable_cname"), default=False)
        if disable_cname:
            continue

        search_domain = as_str(
            row.get("search_domain", row.get("searchdomain", row.get("domain", "")))
        ).lower().strip().rstrip(".")
        if not hostname or not search_domain:
            continue

        cname = f"{hostname}.{search_domain}".rstrip(".")
        target = (dns_name or hostname).rstrip(".")
        if not cname or not target or cname == target:
            continue

        nodes_cname_by_alias[cname].append((target, f"nodes row={row_hint}"))

        extra_cnames = _split_fqdn_list(row.get("extra_cnames"))
        for extra_cname in extra_cnames:
            if not extra_cname or extra_cname == target:
                continue
            nodes_cname_by_alias[extra_cname].append((target, f"nodes extra_cnames row={row_hint}"))

    caddy_target = as_str(caddy_host).lower().strip().rstrip(".")
    tailnet_domain = as_str(tailnet_domain).lower().strip().rstrip(".")

    service_cname_candidates: dict[str, list[tuple[str, str, bool, str]]] = defaultdict(list)
    for service_idx, row in services_df.iterrows():
        row_hint = _sheet_row_hint(service_idx)
        ingress = as_str(row.get("ingress")).lower()
        frontend_hostname = as_str(row.get("frontend_hostname")).lower().rstrip(".")
        if not frontend_hostname:
            continue

        exposure = _normalize_exposure_strict(row.get("exposure"), row_hint=row_hint)
        if exposure not in exposures:
            continue

        default_cname_target = parse_bool(row.get("default_cname_target"), default=False)
        extra_cnames = _split_fqdn_list(row.get("extra_cnames"))

        alias = frontend_hostname
        target = ""

        if exposure == "private":
            if not tailnet_domain:
                raise RuntimeError(
                    f"Services row {row_hint}: private exposure requires --tailnet / tailscale.tailnet_domain"
                )

            if ingress == "caddy":
                target = f"caddy.{tailnet_domain}".rstrip(".")
            else:
                direct_target = as_str(row.get("hostname")).lower().rstrip(".")
                if not direct_target:
                    raise RuntimeError(
                        f"Services row {row_hint}: private direct service requires a hostname target"
                    )
                direct_target_label = _first_hostname_label(direct_target)
                if not direct_target_label:
                    raise RuntimeError(
                        f"Services row {row_hint}: private direct service hostname target is invalid"
                    )
                target = f"{direct_target_label}.{tailnet_domain}".rstrip(".")

        elif exposure == "local":
            if ingress == "caddy":
                if not caddy_target:
                    raise RuntimeError(
                        f"Services row {row_hint}: local caddy service requires caddy host"
                    )
                target = caddy_target
            else:
                direct_target = as_str(row.get("hostname")).lower().rstrip(".")
                if not direct_target:
                    raise RuntimeError(
                        f"Services row {row_hint}: local direct service requires a hostname target"
                    )
                target = direct_target
        else:
            continue

        service_aliases = [alias, *extra_cnames]
        for service_alias in dict.fromkeys(service_aliases):
            service_cname_candidates[service_alias].append((target, ingress, default_cname_target, row_hint))
            _trace(
                (
                    f"Services row {row_hint}: candidate CNAME {service_alias} -> {target} "
                    f"(ingress={ingress or 'unset'}, exposure={exposure}, "
                    f"default_cname_target={default_cname_target})"
                ),
                service_alias,
                frontend_hostname,
                target,
            )

    def _format_service_entries(entries: list[tuple[str, str, bool, str]]) -> str:
        return "; ".join(
            (
                f"{target} (ingress={ingress or 'unset'}, row={row_hint}, "
                f"default_cname_target={'true' if is_default else 'false'})"
            )
            for target, ingress, is_default, row_hint in entries
        )

    resolved_alias_targets: dict[str, str] = {}
    conflicts: list[str] = []

    all_aliases = sorted(
        set(nodes_cname_by_alias.keys()) | set(service_cname_candidates.keys()),
        key=str.lower,
    )

    for alias in all_aliases:
        node_entries = nodes_cname_by_alias.get(alias, [])
        service_entries = service_cname_candidates.get(alias, [])

        if len(node_entries) > 1:
            node_details = "; ".join(f"{target} ({source})" for target, source in node_entries)
            conflicts.append(
                f"- {alias} appears {len(node_entries)}x in Nodes, which is invalid ({node_details})"
            )
            continue

        if node_entries and service_entries:
            node_details = "; ".join(f"{target} ({source})" for target, source in node_entries)
            service_details = _format_service_entries(service_entries)
            conflicts.append(
                f"- {alias} appears in both Nodes and Services; this is invalid "
                f"(Nodes: {node_details}; Services: {service_details})"
            )
            continue

        if node_entries:
            resolved_alias_targets[alias] = node_entries[0][0]
            continue

        if not service_entries:
            continue

        distinct_targets: list[str] = []
        for target, _, _, _ in service_entries:
            if target not in distinct_targets:
                distinct_targets.append(target)

        if len(distinct_targets) == 1:
            resolved_alias_targets[alias] = distinct_targets[0]
            continue

        default_entries = [entry for entry in service_entries if entry[2]]
        if len(default_entries) == 1:
            resolved_alias_targets[alias] = default_entries[0][0]
            continue

        if not sys.stdin.isatty():
            if len(default_entries) == 0:
                reason = "no rows have default_cname_target=true"
            else:
                reason = f"{len(default_entries)} rows have default_cname_target=true"
            conflicts.append(
                f"- {alias} has multiple Services targets and cannot be resolved non-interactively: "
                f"{reason}. Candidates: {_format_service_entries(service_entries)}"
            )
            continue

        print(f"\nConflict: frontend hostname {alias!r} maps to multiple service targets:")
        for idx, target in enumerate(distinct_targets, 1):
            target_entries = [entry for entry in service_entries if entry[0] == target]
            print(f"  [{idx}] {target} <- {_format_service_entries(target_entries)}")

        while True:
            raw = input(f"Choose target for {alias!r} [1-{len(distinct_targets)}]: ").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(distinct_targets):
                resolved_alias_targets[alias] = distinct_targets[int(raw) - 1]
                break
            print(f"  Please enter a number between 1 and {len(distinct_targets)}.")

    if conflicts:
        raise RuntimeError(
            "Invalid CNAME alias conflicts detected. "
            "Update the network source data to remove/fix these entries:\n"
            + "\n".join(conflicts)
        )

    cname_records = sorted(
        (f"{alias},{target}" for alias, target in resolved_alias_targets.items()),
        key=str.lower,
    )

    dns_hosts_toml = _toml_string_array(a_records)
    dns_cname_records_toml = _toml_string_array(cname_records)

    return render_jinja_template(
        template_path=template_path,
        context={
            "dns_hosts_toml": dns_hosts_toml,
            "dns_cname_records_toml": dns_cname_records_toml,
            "a_record_count": len(a_records),
            "cname_record_count": len(cname_records),
        },
    )


def _apply_to_pihole(*, local_path: Path, username: str, host: str, use_sudo: bool) -> None:
    require_command("scp")
    require_command("ssh")

    remote_final_path = "/etc/pihole/pihole.toml"
    target = f"{username}@{host}"

    control_path = ssh_control_path(prefix="dns-pihole", username=username, host=host)
    ssh_args = ssh_base_args(control_path=control_path, port=22, identity_file=None)
    scp_args_list = scp_base_args(control_path=control_path, port=22, identity_file=None)

    ssh_start_master(ssh_args=ssh_args, target=target, env=None)
    try:
        if use_sudo:
            remote_tmp_path = "/tmp/pihole.toml"
            subprocess.run([*scp_args_list, str(local_path), f"{target}:{remote_tmp_path}"], check=True)
            ssh_run(
                ssh_args=ssh_args,
                target=target,
                command=f"sudo install -m 0644 {remote_tmp_path} {remote_final_path}",
                env=None,
            )
            ssh_run(ssh_args=ssh_args, target=target, command="sudo pihole reloaddns", env=None)
        else:
            subprocess.run([*scp_args_list, str(local_path), f"{target}:{remote_final_path}"], check=True)
            ssh_run(ssh_args=ssh_args, target=target, command="pihole reloaddns", env=None)
    finally:
        ssh_stop_master(ssh_args=ssh_args, target=target, env=None)


# ---------------------------
# CLI
# ---------------------------


def build_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[1]
    default_pihole_template = repo_root / "templates" / "pihole" / "pihole.toml.j2"
    default_pihole_output = repo_root / "generated" / "pihole" / "pihole.toml"
    default_dns_output_dir = repo_root / "generated" / "dnscontrol"

    config_path, config = pre_parse_config(argv)
    globals_cfg = get_effective_table(config, "globals", legacy_root_fallback=True)
    dns_cfg = get_effective_table(config, "dns", legacy_root_fallback=False)
    dnscontrol_cfg = get_effective_table(config, "dnscontrol", legacy_root_fallback=False)
    pihole_cfg = get_effective_table(config, "pihole", legacy_root_fallback=False)
    caddy_cfg = get_effective_table(config, "caddy", legacy_root_fallback=False)
    tailscale_cfg = get_effective_table(config, "tailscale", legacy_root_fallback=False)

    effective_dnscontrol_cfg = {**dnscontrol_cfg, **dns_cfg}
    effective_pihole_cfg = {**pihole_cfg, **dns_cfg}

    default_zones = _load_zone_list(dns_cfg=effective_dnscontrol_cfg, caddy_cfg=caddy_cfg)
    default_dns_output_dir_cfg = Path(
        get_config_value(effective_dnscontrol_cfg, "output_dir", str(default_dns_output_dir))
    )

    parser = argparse.ArgumentParser(
        description=(
            "Unified DNS manager for Cloudflare public records and internal Pi-hole records "
            "using strict exposure values: public/private/local."
        )
    )
    parser.add_argument("--config", type=Path, default=config_path)

    parser.add_argument(
        "--target",
        action="append",
        choices=["public", "private", "local", "internal", "all"],
        default=["all"],
        help=(
            "Generation targets (repeatable). 'internal' means private+local. "
            "Defaults to all."
        ),
    )

    parser.add_argument(
        "--sheet-url",
        default=get_config_value(globals_cfg, "sheet_url", DEFAULT_SHEET_URL),
        help="Google Sheets CSV export URL containing gid=0 that will be replaced with tab-specific gids.",
    )
    parser.add_argument(
        "--services-gid",
        type=int,
        default=int(get_config_value(globals_cfg, "services_gid", 0)),
        help="GID for Services sheet",
    )
    parser.add_argument(
        "--nodes-gid",
        type=int,
        default=int(get_config_value(globals_cfg, "nodes_gid", 344016240)),
        help="GID for Nodes sheet",
    )
    parser.add_argument(
        "--zones-gid",
        type=int,
        default=int(get_config_value(globals_cfg, "zones_gid", 0)),
        help="GID for Zones sheet",
    )

    parser.add_argument(
        "--public-ip",
        default=str(
            get_config_value(
                effective_dnscontrol_cfg,
                "public_ip",
                get_config_value(globals_cfg, "public_ip", ""),
            )
        ),
        help="Public IPv4 used for generated Cloudflare records",
    )
    parser.add_argument(
        "--zone",
        action="append",
        dest="zones",
        default=list(default_zones),
        help="Managed DNS zone (repeatable). Defaults to [dnscontrol].zones + [caddy].caddy_zones.",
    )
    parser.add_argument(
        "--dnsconfig-output",
        type=Path,
        default=Path(
            get_config_value(
                effective_dnscontrol_cfg,
                "dnsconfig_output",
                str(default_dns_output_dir_cfg / "dnsconfig.js"),
            )
        ),
        help="Output path for generated dnsconfig.js",
    )
    parser.add_argument(
        "--creds-output",
        type=Path,
        default=Path(
            get_config_value(
                effective_dnscontrol_cfg,
                "creds_output",
                str(default_dns_output_dir_cfg / "creds.json"),
            )
        ),
        help="Output path for generated creds.json",
    )
    parser.add_argument(
        "--dnscontrol-command",
        default=str(get_config_value(effective_dnscontrol_cfg, "dnscontrol_command", "dnscontrol")),
        help="dnscontrol executable used for public apply",
    )
    parser.add_argument(
        "--cloudflare-api-token",
        default=str(get_config_value(effective_dnscontrol_cfg, "cloudflare_api_token", "")),
    )
    parser.add_argument(
        "--cloudflare-account-id",
        default=str(get_config_value(effective_dnscontrol_cfg, "cloudflare_account_id", "")),
    )
    parser.add_argument(
        "--cloudflare-token-env",
        default=str(get_config_value(effective_dnscontrol_cfg, "cloudflare_token_env", "CLOUDFLARE_API_TOKEN")),
    )
    parser.add_argument(
        "--cloudflare-account-id-env",
        default=str(
            get_config_value(
                effective_dnscontrol_cfg,
                "cloudflare_account_id_env",
                "CLOUDFLARE_ACCOUNT_ID",
            )
        ),
    )

    parser.add_argument(
        "--template",
        type=Path,
        default=Path(get_config_value(effective_pihole_cfg, "template", str(default_pihole_template))),
        help="Path to Pi-hole TOML Jinja template",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(get_config_value(effective_pihole_cfg, "output", str(default_pihole_output))),
        help="Path to rendered Pi-hole TOML output",
    )
    parser.add_argument(
        "--pihole-user",
        default=get_config_value(effective_pihole_cfg, "pihole_user", None),
        help="SSH username for Pi-hole host used during apply",
    )
    parser.add_argument(
        "--pihole-host",
        default=get_config_value(effective_pihole_cfg, "pihole_host", None),
        help="SSH hostname/IP for Pi-hole host used during apply",
    )

    default_use_sudo = bool(get_config_value(effective_pihole_cfg, "use_sudo", False))
    parser.add_argument("--sudo", dest="use_sudo", action="store_true", default=default_use_sudo)
    parser.add_argument("--no-sudo", dest="use_sudo", action="store_false")

    parser.add_argument(
        "--tailnet",
        default=get_config_value(tailscale_cfg, "tailnet_domain", ""),
        help="Tailscale tailnet domain used by private DNS records",
    )
    parser.add_argument(
        "--trace-hostname",
        default=get_config_value(effective_pihole_cfg, "trace_hostname", None),
        help="Trace generation decisions for a specific hostname/alias",
    )

    parser.add_argument(
        "--_debug",
        dest="debug",
        action="store_true",
        default=bool(get_config_value(effective_dnscontrol_cfg, "debug", False))
        or bool(get_config_value(effective_pihole_cfg, "debug", False)),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--_apply", dest="apply", action="store_true", help=argparse.SUPPRESS)

    return parser


def _expand_targets(values: list[str]) -> set[str]:
    targets: set[str] = set()
    for value in values:
        if value == "all":
            targets.update({"public", "private", "local"})
        elif value == "internal":
            targets.update({"private", "local"})
        else:
            targets.add(value)
    return targets


def _resolve_cloudflare_credentials(args: argparse.Namespace) -> tuple[str, str]:
    cloudflare_api_token = as_str(args.cloudflare_api_token)
    cloudflare_account_id = as_str(args.cloudflare_account_id)
    cloudflare_token_env = as_str(args.cloudflare_token_env)
    cloudflare_account_id_env = as_str(args.cloudflare_account_id_env)

    if not cloudflare_api_token and cloudflare_token_env:
        cloudflare_api_token = as_str(os.environ.get(cloudflare_token_env))
    if not cloudflare_account_id and cloudflare_account_id_env:
        cloudflare_account_id = as_str(os.environ.get(cloudflare_account_id_env))

    return cloudflare_api_token, cloudflare_account_id


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(argv)
    args = parser.parse_args(argv)

    targets = _expand_targets(list(args.target or ["all"]))

    config_path = args.config.expanduser().resolve()
    dnsconfig_output = resolve_path_relative_to_config(config_path, args.dnsconfig_output)
    creds_output = resolve_path_relative_to_config(config_path, args.creds_output)
    template_path = resolve_path_relative_to_config(config_path, args.template)
    output_path = resolve_path_relative_to_config(config_path, args.output)

    if int(args.services_gid) <= 0:
        print("Error: services_gid must be a positive integer", file=sys.stderr)
        return 2

    try:
        services_df = get_sheet_df(args.sheet_url, int(args.services_gid), 30.0, "Services")
        services_df = df_with_normalized_columns(services_df)
    except Exception as exc:
        print(f"Error: failed to load services sheet: {exc}", file=sys.stderr)
        return 1

    for idx, row in services_df.iterrows():
        row_hint = _sheet_row_hint(idx)
        try:
            _normalize_exposure_strict(row.get("exposure"), row_hint=row_hint)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    generated_any = False

    if "public" in targets:
        public_ip = as_str(args.public_ip)
        if not public_ip:
            print(
                "Error: public_ip is required for public target (set [globals].public_ip or pass --public-ip)",
                file=sys.stderr,
            )
            return 2

        zones = sorted({_normalize_name(zone) for zone in args.zones if _normalize_name(zone)}, key=str.lower)
        if not zones:
            print(
                "Error: at least one DNS zone is required for public target (set [dns].zones/[dnscontrol].zones)",
                file=sys.stderr,
            )
            return 2

        try:
            external_zones = _load_external_zones_from_sheet(
                sheet_url=str(args.sheet_url),
                zones_gid=int(args.zones_gid),
                debug=bool(args.debug),
            )
        except Exception as exc:
            print(f"Error: failed to load zones sheet: {exc}", file=sys.stderr)
            return 1

        if not external_zones:
            print("Error: no zones with 'external' DNS view found in Zones sheet", file=sys.stderr)
            return 2

        zones = sorted(set(zones) & set(external_zones), key=str.lower)
        if not zones:
            print(
                "Error: none of the configured zones have 'external' in DNS Views on Zones sheet",
                file=sys.stderr,
            )
            return 2

        cloudflare_api_token, cloudflare_account_id = _resolve_cloudflare_credentials(args)

        try:
            records = _collect_public_records(
                services_df=services_df,
                zones=zones,
                debug=bool(args.debug),
            )
            dnsconfig_content = _render_dnsconfig(zones=zones, public_ip=public_ip, records=records)
            creds_content = _render_creds_json(
                apitoken=cloudflare_api_token or None,
                accountid=cloudflare_account_id or None,
            )
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        dnsconfig_output.parent.mkdir(parents=True, exist_ok=True)
        creds_output.parent.mkdir(parents=True, exist_ok=True)
        dnsconfig_output.write_text(dnsconfig_content, encoding="utf-8")
        creds_output.write_text(creds_content, encoding="utf-8")

        print(f"Generated {dnsconfig_output}")
        print(f"Generated {creds_output}")
        print(f"Generated {len(records)} public record(s) across {len(zones)} zone(s)")
        generated_any = True

        if args.apply:
            if not cloudflare_api_token:
                print(
                    "Error: public apply requires Cloudflare API token (env or --cloudflare-api-token)",
                    file=sys.stderr,
                )
                return 2
            try:
                require_command(str(args.dnscontrol_command))
                cmd = [
                    str(args.dnscontrol_command),
                    "push",
                    "--config",
                    str(dnsconfig_output),
                    "--creds",
                    str(creds_output),
                ]
                result = subprocess.run(cmd, check=True, text=True, capture_output=True)
                if result.stdout:
                    print(result.stdout.strip())
                if result.stderr:
                    print(result.stderr.strip(), file=sys.stderr)
                print("Applied public DNS changes with dnscontrol push")
            except subprocess.CalledProcessError as exc:
                if exc.stdout:
                    print(exc.stdout.strip())
                if exc.stderr:
                    print(exc.stderr.strip(), file=sys.stderr)
                print(f"Error: dnscontrol push failed (exit code {exc.returncode})", file=sys.stderr)
                return 1
            except Exception as exc:
                print(f"Error: public apply failed: {exc}", file=sys.stderr)
                return 1
        else:
            print("Dry run (public apply disabled): no Cloudflare provider changes made")

    internal_exposures = targets & {"private", "local"}
    if internal_exposures:
        if template_path == output_path:
            print(
                "Error: --output resolves to the same path as --template; refusing to overwrite template.",
                file=sys.stderr,
            )
            return 2

        try:
            config = load_toml_or_exit(config_path)
            globals_cfg = get_effective_table(config, "globals", legacy_root_fallback=True)

            caddy_host = str(get_config_value(globals_cfg, "caddy_host", "")).strip()
            if not caddy_host:
                caddy_host = str(get_config_value(globals_cfg, "caddy_hostname", "")).strip()

            rendered = _render_internal_config(
                sheet_url=str(args.sheet_url),
                nodes_gid=int(args.nodes_gid),
                services_gid=int(args.services_gid),
                template_path=template_path,
                caddy_host=caddy_host,
                tailnet_domain=str(getattr(args, "tailnet", "") or "").strip(),
                exposures=internal_exposures,
                trace_hostname=(str(args.trace_hostname) if args.trace_hostname else None),
                debug=bool(args.debug),
            )
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
        print(f"Rendered {output_path} from template {template_path}")
        generated_any = True

        if args.apply:
            if not args.pihole_user or not args.pihole_host:
                print(
                    "Error: internal apply requires --pihole-user and --pihole-host (or [dns]/[pihole] config)",
                    file=sys.stderr,
                )
                return 2
            try:
                resolver = build_resolver(config)
                resolved_pihole_host = resolver.resolve(str(args.pihole_host))
                _apply_to_pihole(
                    local_path=output_path,
                    username=str(args.pihole_user),
                    host=str(resolved_pihole_host),
                    use_sudo=bool(args.use_sudo),
                )
            except Exception as exc:
                print(f"Error: failed applying internal DNS to Pi-hole: {exc}", file=sys.stderr)
                return 1
            print("Applied internal DNS config to Pi-hole and reloaded DNS")
        else:
            print("Dry run (internal apply disabled): no Pi-hole remote changes made")

    if not generated_any:
        print("Nothing to do: no targets selected", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
