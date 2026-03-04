from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

import pandas as pd

from .config import (
    DEFAULT_SHEET_URL,
    get_config_value,
    get_effective_table,
    get_table,
    load_toml_or_exit,
    pre_parse_config,
    render_jinja_template,
    resolve_path_relative_to_config,
)
from .sheets import as_str, build_sheet_url, df_with_normalized_columns, parse_bool
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


def build_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    tool_dir = Path(__file__).resolve().parent / "pihole"
    config_path, config = pre_parse_config(argv)
    logger.debug("pihole: config_path=%s", config_path)
    globals_cfg = get_table(config, "globals")
    tool_cfg = get_table(config, "pihole")

    parser = argparse.ArgumentParser(
        description=(
            "Generate Pi-hole v6 TOML config from Google Sheets by rendering a Jinja2 template. "
            "Populates dns.hosts from the Nodes tab and dns.cnameRecords from the Services tab "
            "(and optional Nodes CNAMEs)."
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
        default=get_config_value(
            globals_cfg,
            "sheet_url",
            DEFAULT_SHEET_URL,
        ),
        help="Google Sheets CSV export URL containing 'gid=0' that will be replaced with the Nodes/Services GIDs.",
    )
    parser.add_argument(
        "--nodes-gid",
        type=int,
        default=int(get_config_value(globals_cfg, "nodes_gid", 344016240)),
        help="GID for Nodes sheet",
    )
    parser.add_argument(
        "--services-gid",
        type=int,
        default=int(get_config_value(globals_cfg, "services_gid", get_config_value(globals_cfg, "dns_gid", 0))),
        help="GID for Services sheet (used to generate CNAME records)",
    )
    # Backward-compatible alias for older configs/flags.
    parser.add_argument(
        "--dns-gid",
        dest="services_gid",
        type=int,
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--template",
        type=Path,
        default=Path(get_config_value(tool_cfg, "template", str(tool_dir / "pihole.toml.j2"))),
        help="Path to the Jinja2 template TOML (default: pihole.toml.j2 next to this script)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(get_config_value(tool_cfg, "output", str(tool_dir / "pihole.toml"))),
        help="Path to write the rendered TOML (default: pihole.toml next to this script)",
    )

    parser.add_argument(
        "--pihole-user",
        default=get_config_value(tool_cfg, "pihole_user", None),
        help="SSH username for the Pi-hole instance (used with --apply)",
    )
    parser.add_argument(
        "--pihole-host",
        default=get_config_value(tool_cfg, "pihole_host", None),
        help="SSH hostname/IP for the Pi-hole instance (used with --apply)",
    )

    default_use_sudo = bool(get_config_value(tool_cfg, "use_sudo", False))
    parser.add_argument(
        "--sudo",
        dest="use_sudo",
        action="store_true",
        default=default_use_sudo,
        help="Use sudo on the Pi-hole host when applying (default from config)",
    )
    parser.add_argument(
        "--no-sudo",
        dest="use_sudo",
        action="store_false",
        help="Do not use sudo on the Pi-hole host when applying",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "If set, scp the rendered config to /etc/pihole/pihole.toml on the Pi-hole instance "
            "and run 'pihole reloaddns' via ssh."
        ),
    )

    return parser


def render_config(
    *,
    sheet_url: str,
    nodes_gid: int,
    services_gid: int,
    template_path: Path,
    caddy_hostname: str,
) -> str:
    if not template_path.exists():
        raise RuntimeError(f"template not found: {template_path}")

    logger.debug(
        "pihole: render_config nodes_gid=%s services_gid=%s template=%s",
        nodes_gid,
        services_gid,
        template_path,
    )

    nodes_url = build_sheet_url(sheet_url, int(nodes_gid))
    services_url = build_sheet_url(sheet_url, int(services_gid))
    logger.debug("pihole: nodes_url=%s", nodes_url)
    logger.debug("pihole: services_url=%s", services_url)

    try:
        nodes_df = pd.read_csv(nodes_url)
        services_df = pd.read_csv(services_url)
    except Exception as exc:
        raise RuntimeError(f"error loading sheets: {exc}") from exc

    nodes_df = df_with_normalized_columns(nodes_df)

    a_records: list[str] = []
    nodes_cname_records_set: set[str] = set()

    for _, row in nodes_df.iterrows():
        dns_name = as_str(row.get("dns_name")).lower().rstrip(".")
        hostname = as_str(row.get("hostname")).lower().rstrip(".")
        ip = as_str(row.get("ip_address"))

        # Preserve legacy behavior: prefer explicit DNS name (often FQDN), otherwise use hostname.
        host_for_a = dns_name or hostname
        if ip and host_for_a:
            a_records.append(f"{ip} {host_for_a}")

        # Optional Nodes-derived CNAMEs.
        # Column name in sheet: "Disable CNAME" -> normalized: disable_cname
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
        nodes_cname_records_set.add(f"{cname},{target}")

    logger.debug("pihole: a_records=%d", len(a_records))

    services_df = df_with_normalized_columns(services_df)

    cname_records_set: set[str] = set(nodes_cname_records_set)
    for _, row in services_df.iterrows():
        enabled = parse_bool(row.get("frontend_enabled"), default=False)
        if not enabled:
            continue

        ingress = as_str(row.get("ingress")).lower()
        frontend_hostname = as_str(row.get("frontend_hostname")).lower().rstrip(".")
        if not frontend_hostname:
            continue

        if ingress == "dstnat":
            target = as_str(row.get("hostname")).lower().rstrip(".")
            if not target:
                continue
            cname_records_set.add(f"{frontend_hostname},{target}")
        elif ingress == "caddy":
            target = (caddy_hostname or "").strip().lower().rstrip(".")
            if not target:
                raise RuntimeError(
                    "caddy hostname is required to generate ingress=caddy CNAME records; "
                    "set globals.caddy_hostname"
                )
            cname_records_set.add(f"{frontend_hostname},{target}")
        else:
            # Ignore other ingress types.
            continue

    cname_records = sorted(cname_records_set, key=str.lower)
    logger.debug("pihole: cname_records=%d", len(cname_records))

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

    logger.debug(
        "pihole: applying local_path=%s target=%s sudo=%s",
        local_path,
        target,
        use_sudo,
    )

    control_path = ssh_control_path(prefix="pihole", username=username, host=host)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(argv)
    args = parser.parse_args(argv)

    logger.debug("pihole: argv=%r", argv)

    config_path: Path = args.config.expanduser().resolve()

    template_path = resolve_path_relative_to_config(config_path, args.template)
    output_path = resolve_path_relative_to_config(config_path, args.output)

    logger.debug("pihole: template_path=%s output_path=%s", template_path, output_path)

    if template_path == output_path:
        print(
            "Error: --output resolves to the same path as --template; refusing to overwrite the template.",
            file=sys.stderr,
        )
        return 2

    if output_path.suffix in {".j2", ".jinja", ".jinja2"}:
        print(f"Warning: output path looks like a template: {output_path}", file=sys.stderr)

    try:
        config = load_toml_or_exit(config_path)
        globals_cfg = get_effective_table(config, "globals", legacy_root_fallback=True)

        caddy_hostname = str(get_config_value(globals_cfg, "caddy_hostname", "")).strip()

        rendered = render_config(
            sheet_url=str(args.sheet_url),
            nodes_gid=int(args.nodes_gid),
            services_gid=int(getattr(args, "services_gid")),
            template_path=template_path,
            caddy_hostname=caddy_hostname,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"Rendered {output_path} from template {template_path}")

    logger.debug("pihole: wrote rendered config (%d bytes)", len(rendered.encode("utf-8")))

    if args.apply:
        if not args.pihole_user or not args.pihole_host:
            print(
                "Error: --apply requires --pihole-user and --pihole-host (or pihole_user/pihole_host in config)",
                file=sys.stderr,
            )
            return 2
        try:
            _apply_to_pihole(
                local_path=output_path,
                username=str(args.pihole_user),
                host=str(args.pihole_host),
                use_sudo=bool(args.use_sudo),
            )
        except Exception as exc:
            print(f"Error: failed applying to Pi-hole: {exc}", file=sys.stderr)
            return 1
        print("Applied config to Pi-hole and reloaded DNS")
    else:
        remote_final_path = "/etc/pihole/pihole.toml"
        print("Dry run (no --apply): no remote changes made")
        print(f"- generated: {output_path}")

        if not args.pihole_user or not args.pihole_host:
            print("- would apply: skipped (missing --pihole-user/--pihole-host)")
            print("- hint: set pihole_user/pihole_host in config.toml or pass the flags")
        else:
            target = f"{str(args.pihole_user)}@{str(args.pihole_host)}"
            if bool(args.use_sudo):
                print(f"- would scp: {output_path} -> {target}:/tmp/pihole.toml")
                print(
                    f"- would ssh: {target}: sudo install -m 0644 /tmp/pihole.toml {remote_final_path}"
                )
                print(f"- would ssh: {target}: sudo pihole reloaddns")
            else:
                print(f"- would scp: {output_path} -> {target}:{remote_final_path}")
                print(f"- would ssh: {target}: pihole reloaddns")

        print("Re-run with --apply to perform these actions.")

    return 0

