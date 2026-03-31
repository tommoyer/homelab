from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

from .cli_common import (
    add_apply_argument,
    add_sheet_arguments,
    bootstrap_config_and_logging,
    build_base_parser,
)
from .config import (
    DEFAULT_SHEET_URL,
    get_config_value,
    get_effective_table,
    get_table,
    load_toml_or_exit,
    render_jinja_template,
    resolve_path_relative_to_config,
)
from .resolver import build_resolver
from .sheets import as_str, build_sheet_url, df_with_normalized_columns, get_sheet_df, parse_bool
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
    """Build argument parser for pihole tool using cli_common utilities."""
    repo_root = Path(__file__).resolve().parents[1]
    default_template_dir = repo_root / "templates" / "pihole"
    default_output_dir = repo_root / "generated" / "pihole"
    
    config_path, config, globals_cfg, tool_cfg = bootstrap_config_and_logging(argv, "pihole")
    tailscale_cfg = get_effective_table(config, "tailscale", legacy_root_fallback=False)

    parser = build_base_parser(
        description=(
            "Generate Pi-hole v6 TOML config from Google Sheets by rendering a Jinja2 template. "
            "Populates dns.hosts from the Nodes tab and dns.cnameRecords from the Services tab "
            "(and optional Nodes CNAMEs)."
        ),
        config_path=config_path,
        globals_cfg=globals_cfg,
        tool_cfg=tool_cfg,
    )

    # Add standard sheet arguments
    add_sheet_arguments(
        parser,
        globals_cfg,
        nodes_gid=344016240,
        services_gid=0,
        dns_gid=0,
    )

    # Tool-specific arguments
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(get_config_value(tool_cfg, "template", str(default_template_dir / "pihole.toml.j2"))),
        help="Path to the Jinja2 template TOML (default: templates/pihole/pihole.toml.j2)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(get_config_value(tool_cfg, "output", str(default_output_dir / "pihole.toml"))),
        help="Path to write the rendered TOML (default: generated/pihole/pihole.toml)",
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
        "--trace-hostname",
        default=get_config_value(tool_cfg, "trace_hostname", None),
        help="Trace generation decisions for a specific hostname/alias",
    )

    parser.add_argument(
        "--tailnet",
        default=get_config_value(tailscale_cfg, "tailnet_domain", ""),
        help=(
            "Tailscale tailnet domain (e.g. 'duckbill-frog.ts.net'). "
            "Used for trusted CNAME targets. Defaults to tailscale.tailnet_domain from config."
        ),
    )

    add_apply_argument(
        parser,
        help_text=(
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
    caddy_host: str,
    tailnet_domain: str,
    trace_hostname: str | None = None,
    debug: bool = False,
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
        nodes_df = get_sheet_df(nodes_url, cache_dir=None)
        services_df = get_sheet_df(services_url, cache_dir=None)
    except Exception as exc:
        raise RuntimeError(f"error loading sheets: {exc}") from exc

    nodes_df = df_with_normalized_columns(nodes_df)

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
        print(f"[pihole trace:{scope}] {message}", file=sys.stderr)

    def _sheet_row_hint(index: object) -> str:
        try:
            return str(int(str(index)) + 2)
        except Exception:
            return str(index)

    def _format_service_entries(entries: list[tuple[str, str, bool, str]]) -> str:
        return "; ".join(
            (
                f"{target} (ingress={ingress or 'unset'}, row={row_hint}, "
                f"default_cname_target={'true' if is_default else 'false'})"
            )
            for target, ingress, is_default, row_hint in entries
        )

    a_records: list[str] = []
    nodes_cname_by_alias: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for node_idx, row in nodes_df.iterrows():
        dns_name = as_str(row.get("dns_name")).lower().rstrip(".")
        hostname = as_str(row.get("hostname")).lower().rstrip(".")
        ip = as_str(row.get("ip_address"))
        row_hint = _sheet_row_hint(node_idx)

        # Preserve legacy behavior: prefer explicit DNS name (often FQDN), otherwise use hostname.
        host_for_a = dns_name or hostname
        if ip and host_for_a:
            a_records.append(f"{ip} {host_for_a}")
            _trace(f"Nodes row {row_hint}: add A record {ip} {host_for_a}", hostname, dns_name, host_for_a)

        # Optional Nodes-derived CNAMEs.
        # Column name in sheet: "Disable CNAME" -> normalized: disable_cname
        disable_cname = parse_bool(row.get("disable_cname"), default=False)
        if disable_cname:
            _trace(f"Nodes row {row_hint}: skip CNAME because disable_cname=true", hostname, dns_name)
            continue

        search_domain = as_str(
            row.get("search_domain", row.get("searchdomain", row.get("domain", "")))
        ).lower().strip().rstrip(".")
        if not hostname or not search_domain:
            _trace(
                f"Nodes row {row_hint}: skip CNAME because hostname/search_domain missing",
                hostname,
                dns_name,
            )
            continue

        cname = f"{hostname}.{search_domain}".rstrip(".")
        target = (dns_name or hostname).rstrip(".")
        if not cname or not target or cname == target:
            _trace(
                (
                    f"Nodes row {row_hint}: skip CNAME because cname/target invalid or self-target "
                    f"(cname={cname!r}, target={target!r})"
                ),
                hostname,
                dns_name,
                cname,
                target,
            )
            continue
        nodes_cname_by_alias[cname].append((target, f"nodes row={row_hint}"))
        _trace(f"Nodes row {row_hint}: candidate CNAME {cname} -> {target}", hostname, dns_name, cname, target)

    logger.debug("pihole: a_records=%d", len(a_records))

    services_df = df_with_normalized_columns(services_df)

    service_cname_candidates: dict[str, list[tuple[str, str, bool, str]]] = defaultdict(list)
    for service_idx, row in services_df.iterrows():
        ingress = as_str(row.get("ingress")).lower()
        exposure = as_str(row.get("exposure")).lower()
        frontend_hostname = as_str(row.get("frontend_hostname")).lower().rstrip(".")
        if not frontend_hostname:
            continue

        default_cname_target = parse_bool(row.get("default_cname_target"), default=False)
        row_hint = _sheet_row_hint(service_idx)

        if ingress == "caddy" and exposure == "trusted":
            # Trusted caddy services point to the caddy node's Tailscale MagicDNS name.
            # Extract the short hostname (first label) from the FQDN for CNAME building.
            caddy_short = caddy_host.split(".")[0] if caddy_host else ""
            if not caddy_short:
                raise RuntimeError(
                    "caddy hostname is required to generate ingress=caddy CNAME records; "
                    "set globals.caddy_host"
                )
            if not tailnet_domain:
                raise RuntimeError(
                    "tailnet domain is required to generate trusted CNAME records; "
                    "set tailscale.tailnet_domain or pass --tailnet"
                )
            target = f"{caddy_short}.{tailnet_domain}".rstrip(".")
        elif ingress == "caddy" and exposure == "public":
            # Public caddy services point to caddy.<dns_zone> from the sheet.
            caddy_short = caddy_host.split(".")[0] if caddy_host else ""
            if not caddy_short:
                raise RuntimeError(
                    "caddy hostname is required to generate ingress=caddy CNAME records; "
                    "set globals.caddy_host"
                )
            dns_zone = as_str(row.get("dns_zone")).lower().rstrip(".")
            if not dns_zone:
                raise RuntimeError(
                    f"Services row {row_hint}: ingress=caddy, exposure=public requires a "
                    f"'DNS Zone' column value for frontend_hostname={frontend_hostname!r}"
                )
            target = f"{caddy_short}.{dns_zone}".rstrip(".")
        elif ingress == "direct" and exposure == "trusted":
            # Trusted direct services point to <hostname>.<tailnet>.
            # Extract just the short hostname (first label) from the FQDN.
            backend_hostname = as_str(row.get("hostname")).lower().rstrip(".")
            if not backend_hostname:
                logger.debug(
                    "pihole: skipping service row with frontend_hostname=%r — no target hostname (ingress=%r)",
                    frontend_hostname,
                    ingress,
                )
                _trace(
                    (
                        f"Services row {row_hint}: skip because target hostname missing "
                        f"(frontend={frontend_hostname!r}, ingress={ingress!r})"
                    ),
                    frontend_hostname,
                )
                continue
            short_hostname = backend_hostname.split(".")[0]
            if not tailnet_domain:
                raise RuntimeError(
                    "tailnet domain is required to generate trusted CNAME records; "
                    "set tailscale.tailnet_domain or pass --tailnet"
                )
            target = f"{short_hostname}.{tailnet_domain}".rstrip(".")
        elif ingress == "direct" and exposure == "public":
            # Public direct services point to the backend hostname.
            target = as_str(row.get("hostname")).lower().rstrip(".")
            if not target:
                logger.debug(
                    "pihole: skipping service row with frontend_hostname=%r — no target hostname (ingress=%r)",
                    frontend_hostname,
                    ingress,
                )
                _trace(
                    (
                        f"Services row {row_hint}: skip because target hostname missing "
                        f"(frontend={frontend_hostname!r}, ingress={ingress!r})"
                    ),
                    frontend_hostname,
                )
                continue
        else:
            # For dstnat, blank, or any other ingress/exposure combination,
            # use the hostname column as the target.
            target = as_str(row.get("hostname")).lower().rstrip(".")
            if not target:
                logger.debug(
                    "pihole: skipping service row with frontend_hostname=%r — no target hostname (ingress=%r)",
                    frontend_hostname,
                    ingress,
                )
                _trace(
                    (
                        f"Services row {row_hint}: skip because target hostname missing "
                        f"(frontend={frontend_hostname!r}, ingress={ingress!r})"
                    ),
                    frontend_hostname,
                )
                continue

        service_cname_candidates[frontend_hostname].append((target, ingress, default_cname_target, row_hint))
        _trace(
            (
                f"Services row {row_hint}: candidate CNAME {frontend_hostname} -> {target} "
                f"(ingress={ingress or 'unset'}, default_cname_target={default_cname_target})"
            ),
            frontend_hostname,
            target,
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
            _trace("Resolution: conflict (duplicate Nodes entries)", alias)
            continue

        if node_entries and service_entries:
            node_details = "; ".join(f"{target} ({source})" for target, source in node_entries)
            service_details = _format_service_entries(service_entries)
            conflicts.append(
                f"- {alias} appears in both Nodes and Services; this is invalid "
                f"(Nodes: {node_details}; Services: {service_details})"
            )
            _trace("Resolution: conflict (alias exists in both Nodes and Services)", alias)
            continue

        if node_entries:
            resolved_alias_targets[alias] = node_entries[0][0]
            _trace(f"Resolution: selected Nodes target {node_entries[0][0]}", alias)
            continue

        if not service_entries:
            continue

        distinct_targets: list[str] = []
        for target, _, _, _ in service_entries:
            if target not in distinct_targets:
                distinct_targets.append(target)

        if len(distinct_targets) == 1:
            resolved_alias_targets[alias] = distinct_targets[0]
            _trace(f"Resolution: collapsed duplicate Services rows to target {distinct_targets[0]}", alias)
            continue

        default_entries = [entry for entry in service_entries if entry[2]]
        if len(default_entries) == 1:
            resolved_alias_targets[alias] = default_entries[0][0]
            _trace(
                f"Resolution: selected default Services target {default_entries[0][0]} (default_cname_target=true)",
                alias,
            )
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
            _trace(f"Resolution: conflict in non-interactive mode ({reason})", alias)
            continue

        print(f"\nConflict: frontend hostname {alias!r} maps to multiple service targets:")
        for idx, target in enumerate(distinct_targets, 1):
            target_entries = [entry for entry in service_entries if entry[0] == target]
            print(f"  [{idx}] {target} <- {_format_service_entries(target_entries)}")

        while True:
            raw = input(f"Choose target for {alias!r} [1-{len(distinct_targets)}]: ").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(distinct_targets):
                resolved_alias_targets[alias] = distinct_targets[int(raw) - 1]
                _trace(f"Resolution: selected interactively -> {resolved_alias_targets[alias]}", alias)
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
    if trace_key and trace_key not in resolved_alias_targets:
        _trace("Resolution: hostname not present in final cnameRecords", trace_key)
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

        # Resolve pihole_host through Tailscale if it is a hostname.
        resolver = build_resolver(config)
        if args.pihole_host:
            args.pihole_host = resolver.resolve(str(args.pihole_host))

        caddy_host = str(get_config_value(globals_cfg, "caddy_host", "")).strip()
        if not caddy_host:
            # Legacy fallback for older configs.
            caddy_host = str(get_config_value(globals_cfg, "caddy_hostname", "")).strip()

        tailnet_domain = str(getattr(args, "tailnet", "") or "").strip()

        rendered = render_config(
            sheet_url=str(args.sheet_url),
            nodes_gid=int(args.nodes_gid),
            services_gid=int(getattr(args, "services_gid")),
            template_path=template_path,
            caddy_host=caddy_host,
            tailnet_domain=tailnet_domain,
            trace_hostname=(str(args.trace_hostname) if args.trace_hostname else None),
            debug=bool(args.debug),
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

