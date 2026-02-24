from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import (
    get_config_value,
    get_effective_table,
    load_toml_or_exit,
    resolve_path_relative_to_config,
)
from .ssh import require_command, ssh_control_path, ssh_mux_options


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
    default_config = Path(__file__).resolve().parent / "config.toml"

    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "--config",
        type=Path,
        default=default_config,
        help="Path to TOML config file containing default parameters",
    )
    pre_args, _ = pre_parser.parse_known_args(argv)
    config_path = pre_args.config.expanduser().resolve()
    config = load_toml_or_exit(config_path)
    cfg = get_effective_table(config, "pihole", legacy_root_fallback=True)

    parser = argparse.ArgumentParser(
        description=(
            "Generate Pi-hole v6 TOML config from Google Sheets by rendering a Jinja2 template. "
            "Populates dns.hosts and dns.cnameRecords."
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
            cfg,
            "sheet_url",
            (
                "https://docs.google.com/spreadsheets/d/"
                "1f4emn4uIPscEgOHtgmETODlTvz1eh2xZlnpBBNGQlWA/"
                "export?format=csv&gid=0"
            ),
        ),
        help="Google Sheets CSV export URL containing 'gid=0' that will be replaced with the Nodes/DNS GIDs.",
    )
    parser.add_argument(
        "--nodes-gid",
        type=int,
        default=int(get_config_value(cfg, "nodes_gid", 344016240)),
        help="GID for Nodes sheet",
    )
    parser.add_argument(
        "--dns-gid",
        type=int,
        default=int(get_config_value(cfg, "dns_gid", 95412045)),
        help="GID for DNS sheet",
    )

    parser.add_argument(
        "--template",
        type=Path,
        default=Path(get_config_value(cfg, "template", str(tool_dir / "pihole.toml.j2"))),
        help="Path to the Jinja2 template TOML (default: pihole.toml.j2 next to this script)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(get_config_value(cfg, "output", str(tool_dir / "pihole.toml"))),
        help="Path to write the rendered TOML (default: pihole.toml next to this script)",
    )

    parser.add_argument(
        "--pihole-user",
        default=get_config_value(cfg, "pihole_user", None),
        help="SSH username for the Pi-hole instance (used with --apply)",
    )
    parser.add_argument(
        "--pihole-host",
        default=get_config_value(cfg, "pihole_host", None),
        help="SSH hostname/IP for the Pi-hole instance (used with --apply)",
    )

    default_use_sudo = bool(get_config_value(cfg, "use_sudo", False))
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


def render_config(*, sheet_url: str, nodes_gid: int, dns_gid: int, template_path: Path) -> str:
    if not template_path.exists():
        raise RuntimeError(f"template not found: {template_path}")

    nodes_url = sheet_url.replace("gid=0", f"gid={nodes_gid}")
    dns_url = sheet_url.replace("gid=0", f"gid={dns_gid}")

    try:
        nodes_df = pd.read_csv(nodes_url)
        dns_df = pd.read_csv(dns_url)
    except Exception as exc:
        raise RuntimeError(f"error loading sheets: {exc}") from exc

    a_records: list[str] = []
    for _, row in nodes_df.iterrows():
        hostname_raw = row.get("DNS Name", row.get("Hostname", ""))
        ip_raw = row.get("IP Address", "")

        hostname = "" if pd.isna(hostname_raw) else str(hostname_raw).strip()
        ip = "" if pd.isna(ip_raw) else str(ip_raw).strip()

        if ip and hostname:
            a_records.append(f"{ip} {hostname}")

    cname_records: list[str] = []
    for _, row in dns_df.iterrows():
        record_type = row.get("Record Type")
        if pd.isna(record_type) or str(record_type).strip() != "CNAME":
            continue
        views = str(row.get("DNS Views", "")).lower()
        if "internal" not in views:
            continue

        name_raw = row.get("Record Name", "")
        zone_raw = row.get("Zone", "")
        value_raw = row.get("Value", "")

        name = "" if pd.isna(name_raw) else str(name_raw).strip()
        zone = "" if pd.isna(zone_raw) else str(zone_raw).strip()
        value = "" if pd.isna(value_raw) else str(value_raw).strip()

        if name and zone and value:
            cname_key = f"{name}.{zone}"
            cname_records.append(f"{cname_key},{value}")

    dns_hosts_toml = _toml_string_array(a_records)
    dns_cname_records_toml = _toml_string_array(cname_records)

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_path.name)

    return template.render(
        dns_hosts_toml=dns_hosts_toml,
        dns_cname_records_toml=dns_cname_records_toml,
        a_record_count=len(a_records),
        cname_record_count=len(cname_records),
    )


def _apply_to_pihole(*, local_path: Path, username: str, host: str, use_sudo: bool) -> None:
    require_command("scp")
    require_command("ssh")

    remote_final_path = "/etc/pihole/pihole.toml"
    ssh_target = f"{username}@{host}"

    control_path = ssh_control_path(prefix="pihole", username=username, host=host)
    mux_opts = ssh_mux_options(control_path)

    subprocess.run(["ssh", *mux_opts, "-Nf", ssh_target], check=True)

    try:
        if use_sudo:
            remote_tmp_path = "/tmp/pihole.toml"
            subprocess.run(["scp", *mux_opts, str(local_path), f"{ssh_target}:{remote_tmp_path}"], check=True)
            subprocess.run(
                [
                    "ssh",
                    *mux_opts,
                    ssh_target,
                    "sudo",
                    "install",
                    "-m",
                    "0644",
                    remote_tmp_path,
                    remote_final_path,
                ],
                check=True,
            )
            subprocess.run(["ssh", *mux_opts, ssh_target, "sudo", "pihole", "reloaddns"], check=True)
        else:
            subprocess.run(["scp", *mux_opts, str(local_path), f"{ssh_target}:{remote_final_path}"], check=True)
            subprocess.run(["ssh", *mux_opts, ssh_target, "pihole", "reloaddns"], check=True)
    finally:
        subprocess.run(["ssh", *mux_opts, "-O", "exit", ssh_target], check=False)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(argv)
    args = parser.parse_args(argv)

    config_path: Path = args.config.expanduser().resolve()

    template_path = resolve_path_relative_to_config(config_path, args.template)
    output_path = resolve_path_relative_to_config(config_path, args.output)

    if template_path == output_path:
        print(
            "Error: --output resolves to the same path as --template; refusing to overwrite the template.",
            file=sys.stderr,
        )
        return 2

    if output_path.suffix in {".j2", ".jinja", ".jinja2"}:
        print(f"Warning: output path looks like a template: {output_path}", file=sys.stderr)

    try:
        rendered = render_config(
            sheet_url=str(args.sheet_url),
            nodes_gid=int(args.nodes_gid),
            dns_gid=int(args.dns_gid),
            template_path=template_path,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"Rendered {output_path} from template {template_path}")

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

    return 0
