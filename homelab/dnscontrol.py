from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import (
    DEFAULT_SHEET_URL,
    get_config_value,
    get_effective_table,
    pre_parse_config,
    resolve_path_relative_to_config,
)
from .sheets import as_str, df_with_normalized_columns, get_sheet_df
from .ssh import require_command

logger = logging.getLogger(__name__)


def _normalize_name(value: Any) -> str:
    return as_str(value).lower().rstrip(".")


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


def _load_zone_list(*, dnscontrol_cfg: dict[str, Any], caddy_cfg: dict[str, Any]) -> list[str]:
    zones: list[str] = []

    raw_dnscontrol_zones = dnscontrol_cfg.get("zones")
    if isinstance(raw_dnscontrol_zones, list):
        for item in raw_dnscontrol_zones:
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

    deduped = sorted(set(zones), key=str.lower)
    return deduped


def _load_external_zones_from_sheet(
    *,
    sheet_url: str,
    zones_gid: int,
    debug: bool = False,
) -> list[str]:
    """Fetch the Zones tab and return zones where DNS Views includes 'external'."""
    zones_df = get_sheet_df(sheet_url, int(zones_gid), 30.0, "Zones")

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
                    f"[dnscontrol debug] row {idx}: zone {dns_zone!r} has external DNS view",
                    file=sys.stderr,
                )
        elif debug:
            print(
                f"[dnscontrol debug] row {idx}: zone {dns_zone!r} skipped (views={views!r})",
                file=sys.stderr,
            )

    return sorted(set(external_zones), key=str.lower)


def _collect_public_records(
    *,
    services_df: pd.DataFrame,
    zones: list[str],
    debug: bool,
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen_by_fqdn: dict[str, dict[str, str]] = {}

    for idx, row in services_df.iterrows():
        exposure = _normalize_name(row.get("exposure"))
        if exposure != "public":
            continue

        ingress = _normalize_name(row.get("ingress"))
        if ingress not in {"caddy", "direct"}:
            if debug:
                print(
                    f"[dnscontrol debug] row {idx}: unsupported ingress={ingress!r} for public service; skipping",
                    file=sys.stderr,
                )
            continue

        fqdn = _normalize_name(row.get("frontend_hostname"))
        if not fqdn:
            if debug:
                print(f"[dnscontrol debug] row {idx}: missing frontend_hostname; skipping", file=sys.stderr)
            continue

        zone = _determine_zone(fqdn, zones)
        if not zone:
            raise RuntimeError(
                f"service row {idx} hostname {fqdn!r} does not match any configured dnscontrol zone"
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
                    f"[dnscontrol debug] row {idx}: duplicate public service for {fqdn}; keeping first",
                    file=sys.stderr,
                )
            continue

        seen_by_fqdn[fqdn] = record
        records.append(record)

    return sorted(records, key=lambda item: item["fqdn"])


def _render_dnsconfig(
    *,
    zones: list[str],
    public_ip: str,
    records: list[dict[str, str]],
) -> str:
    grouped: dict[str, list[dict[str, str]]] = {zone: [] for zone in zones}
    for record in records:
        grouped.setdefault(record["zone"], []).append(record)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    lines: list[str] = [
        "// AUTOGENERATED by homelab dnscontrol generator.",
        f"// Generated at {generated_at}",
        "",
        'var REG_NONE = NewRegistrar("none");',
        'var DSP_CLOUDFLARE = NewDnsProvider("cloudflare");',
        "",
        '// Meta settings for individual records.',
        'var CF_PROXY_OFF = {"cloudflare_proxy": "off"};     // Proxy disabled.'
        'var CF_PROXY_ON = {"cloudflare_proxy": "on"};       // Proxy enabled.'
        'var CF_PROXY_FULL = {"cloudflare_proxy": "full"};   // Proxy+Railgun enabled.',
        'var CF_CNAME_FLATTEN_OFF = {"cloudflare_cname_flatten": "off"};  // CNAME flattening disabled (default).',
        'var CF_CNAME_FLATTEN_ON = {"cloudflare_cname_flatten": "on"};    // CNAME flattening enabled (paid plans only).',
        '// CF_COMMENT(comment) - Set a comment on a record (requires CF_MANAGE_COMMENTS).',
        '// CF_TAGS(tag1, tag2, ...) - Set tags on a record (requires CF_MANAGE_TAGS, paid plans only).',
        '',
        '// Per-domain meta settings:',
        '// Proxy default off for entire domain (the default):',
        'var CF_PROXY_DEFAULT_OFF = {"cloudflare_proxy_default": "off"};',
        '// Proxy default on for entire domain:',
        'var CF_PROXY_DEFAULT_ON = {"cloudflare_proxy_default": "on"};',
        '// UniversalSSL off for entire domain:',
        'var CF_UNIVERSALSSL_OFF = { cloudflare_universalssl: "off" };',
        '// UniversalSSL on for entire domain:',
        'var CF_UNIVERSALSSL_ON = { cloudflare_universalssl: "on" };',
        '// Enable comment management for domain (opt-in):',
        'var CF_MANAGE_COMMENTS = { cloudflare_manage_comments: "true" };',
        '// Enable tag management for domain (opt-in, paid plans only):',
        'var CF_MANAGE_TAGS = { cloudflare_manage_tags: "true" };',
        "",
    ]

    for zone in zones:
        zone_records = sorted(grouped.get(zone, []), key=lambda item: item["fqdn"])
        zone_fqdn = f"{zone}."

        # Determine if any apex service needs Cloudflare proxying
        apex_proxy = any(
            r["name"] == "@" and r["ingress"] == "caddy" for r in zone_records
        )

        lines.append(f'D("{zone}", REG_NONE, DnsProvider(DSP_CLOUDFLARE),')

        # Top-level A record for the zone apex
        if apex_proxy:
            apex_meta = json.dumps({"cloudflare_proxy": "on"}, separators=(",", ": "))
            lines.append(f'  A("@", "{public_ip}", {apex_meta}),')
        else:
            lines.append(f'  A("@", "{public_ip}"),')

        # Non-apex records as CNAMEs pointing to the zone apex
        for record in zone_records:
            if record["name"] == "@":
                continue  # Covered by the A record above
            proxy_value = "CF_PROXY_ON" if record["ingress"] == "caddy" else "CF_PROXY_OFF"
            lines.append(
                f'  CNAME("{record["name"]}", "{zone_fqdn}", {proxy_value}),'
            )

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


def build_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[1]
    default_output_dir = repo_root / "generated" / "dnscontrol"
    config_path, config = pre_parse_config(argv)
    globals_cfg = get_effective_table(config, "globals", legacy_root_fallback=True)
    dnscontrol_cfg = get_effective_table(config, "dnscontrol")
    caddy_cfg = get_effective_table(config, "caddy")

    default_zones = _load_zone_list(dnscontrol_cfg=dnscontrol_cfg, caddy_cfg=caddy_cfg)
    default_output_dir_cfg = Path(get_config_value(dnscontrol_cfg, "output_dir", str(default_output_dir)))
    default_dnsconfig_output = Path(
        get_config_value(dnscontrol_cfg, "dnsconfig_output", str(default_output_dir_cfg / "dnsconfig.js"))
    )
    default_creds_output = Path(
        get_config_value(dnscontrol_cfg, "creds_output", str(default_output_dir_cfg / "creds.json"))
    )

    parser = argparse.ArgumentParser(
        description=(
            "Generate dnscontrol inputs (dnsconfig.js + creds.json) from the Services sheet. "
            "Only services where exposure=public and ingress in {caddy,direct} are emitted."
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
        default=get_config_value(globals_cfg, "sheet_url", DEFAULT_SHEET_URL),
        help="Google Sheets CSV export URL containing 'gid=0' that will be replaced with services_gid.",
    )
    parser.add_argument(
        "--services-gid",
        type=int,
        default=int(get_config_value(globals_cfg, "services_gid", 0)),
        help="GID for Services sheet",
    )
    parser.add_argument(
        "--zones-gid",
        type=int,
        default=int(get_config_value(globals_cfg, "zones_gid", 0)),
        help="GID for Zones sheet (used to determine which zones have external DNS views)",
    )
    parser.add_argument(
        "--public-ip",
        default=str(
            get_config_value(
                dnscontrol_cfg,
                "public_ip",
                get_config_value(globals_cfg, "public_ip", ""),
            )
        ),
        help="Public IPv4 address used by generated Cloudflare records",
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
        default=default_dnsconfig_output,
        help="Output path for generated dnsconfig.js",
    )
    parser.add_argument(
        "--creds-output",
        type=Path,
        default=default_creds_output,
        help="Output path for generated creds.json",
    )
    parser.add_argument(
        "--_debug",
        dest="debug",
        action="store_true",
        default=bool(get_config_value(dnscontrol_cfg, "debug", False)),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--_apply",
        dest="apply",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--dnscontrol-command",
        default=str(get_config_value(dnscontrol_cfg, "dnscontrol_command", "dnscontrol")),
        help="dnscontrol executable name/path used when global --apply is enabled",
    )
    parser.add_argument(
        "--cloudflare-api-token",
        default=str(get_config_value(dnscontrol_cfg, "cloudflare_api_token", "")),
        help="Cloudflare API token used to populate creds.json (overrides env lookup)",
    )
    parser.add_argument(
        "--cloudflare-account-id",
        default=str(get_config_value(dnscontrol_cfg, "cloudflare_account_id", "")),
        help="Cloudflare account ID used to populate creds.json",
    )
    parser.add_argument(
        "--cloudflare-token-env",
        default=str(get_config_value(dnscontrol_cfg, "cloudflare_token_env", "CLOUDFLARE_API_TOKEN")),
        help="Environment variable name that stores the Cloudflare API token",
    )
    parser.add_argument(
        "--cloudflare-account-id-env",
        default=str(get_config_value(dnscontrol_cfg, "cloudflare_account_id_env", "CLOUDFLARE_ACCOUNT_ID")),
        help="Environment variable name that stores the Cloudflare account ID",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(argv)
    args = parser.parse_args(argv)

    config_path = args.config.expanduser().resolve()
    dnsconfig_output = resolve_path_relative_to_config(config_path, args.dnsconfig_output)
    creds_output = resolve_path_relative_to_config(config_path, args.creds_output)

    if int(args.services_gid) <= 0:
        print("Error: services_gid must be a positive integer", file=sys.stderr)
        return 2

    public_ip = as_str(args.public_ip)
    if not public_ip:
        print(
            "Error: public_ip is required (set [globals].public_ip, [dnscontrol].public_ip, or pass --public-ip)",
            file=sys.stderr,
        )
        return 2

    zones = sorted({_normalize_name(zone) for zone in args.zones if _normalize_name(zone)}, key=str.lower)
    if not zones:
        print(
            "Error: at least one DNS zone is required (set [dnscontrol].zones or pass --zone)",
            file=sys.stderr,
        )
        return 2

    # Fetch the Zones tab and restrict to zones with "external" in DNS Views.
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
        print(
            "Error: no zones with 'external' DNS view found in Zones sheet",
            file=sys.stderr,
        )
        return 2

    # Only generate records for zones that have an external DNS view.
    zones = sorted(set(zones) & set(external_zones), key=str.lower)
    if not zones:
        print(
            "Error: none of the configured zones have 'external' in DNS Views on the Zones sheet",
            file=sys.stderr,
        )
        return 2

    if args.debug:
        print(f"[dnscontrol debug] external zones from sheet: {external_zones}", file=sys.stderr)
        print(f"[dnscontrol debug] effective zones for generation: {zones}", file=sys.stderr)

    try:
        services_df = get_sheet_df(args.sheet_url, int(args.services_gid), 30.0, "Services")
        services_df = df_with_normalized_columns(services_df)
    except Exception as exc:
        print(f"Error: failed to load services sheet: {exc}", file=sys.stderr)
        return 1

    try:
        cloudflare_api_token = as_str(args.cloudflare_api_token)
        cloudflare_account_id = as_str(args.cloudflare_account_id)
        cloudflare_token_env = as_str(args.cloudflare_token_env)
        cloudflare_account_id_env = as_str(args.cloudflare_account_id_env)
        if not cloudflare_api_token and cloudflare_token_env:
            cloudflare_api_token = as_str(os.environ.get(cloudflare_token_env))
        if not cloudflare_account_id and cloudflare_account_id_env:
            cloudflare_account_id = as_str(os.environ.get(cloudflare_account_id_env))

        records = _collect_public_records(
            services_df=services_df,
            zones=zones,
            debug=bool(args.debug),
        )
        dnsconfig_content = _render_dnsconfig(
            zones=zones,
            public_ip=public_ip,
            records=records,
        )
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

    if args.apply:
        if not cloudflare_api_token:
            print(
                "Error: apply mode requires a Cloudflare API token (set [dnscontrol].cloudflare_token_env "
                "to an environment variable name, set that env var, or pass --cloudflare-api-token).",
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
            result = subprocess.run(
                cmd,
                check=True,
                text=True,
                capture_output=True,
            )
            if result.stdout:
                print(result.stdout.strip())
            if result.stderr:
                print(result.stderr.strip(), file=sys.stderr)
            print("Applied DNS changes with dnscontrol push")
        except subprocess.CalledProcessError as exc:
            if exc.stdout:
                print(exc.stdout.strip())
            if exc.stderr:
                print(exc.stderr.strip(), file=sys.stderr)
            print(f"Error: dnscontrol push failed (exit code {exc.returncode})", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"Error: dnscontrol apply failed: {exc}", file=sys.stderr)
            return 1
    else:
        print("Dry run (apply mode disabled): no DNS provider changes made")
        print(f"- generated: {dnsconfig_output}")
        print(f"- generated: {creds_output}")
        print(
            f"- would run: {args.dnscontrol_command} push --config {dnsconfig_output} --creds {creds_output}"
        )
        if not cloudflare_api_token:
            print(
                "- would fail to apply: Cloudflare token not resolved (set [dnscontrol].cloudflare_token_env "
                "or pass --cloudflare-api-token)"
            )
        print("Re-run with global --apply to perform these actions.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
