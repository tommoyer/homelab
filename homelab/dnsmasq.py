from __future__ import annotations

import argparse
import json
import logging
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
    load_toml_or_exit,
    pre_parse_config,
    render_jinja_template,
    resolve_path_relative_to_config,
)
from .sheets import as_str, build_sheet_url, df_with_normalized_columns
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


def _normalize_name(value: str) -> str:
    return (value or "").strip().lower().rstrip(".")


def _name_candidates(value: str) -> list[str]:
    normalized = _normalize_name(value)
    if not normalized:
        return []
    out = [normalized]
    if "." in normalized:
        out.append(normalized.split(".", 1)[0])
    return list(dict.fromkeys(out))


def _extract_tailscale_ip(peer: dict[str, Any]) -> str | None:
    ips = peer.get("TailscaleIPs")
    if isinstance(ips, list):
        for item in ips:
            value = as_str(item)
            if value:
                return value
    return None


def _build_tailscale_lookup(status: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}

    self_peer = status.get("Self")
    if isinstance(self_peer, dict):
        peer_ip = _extract_tailscale_ip(self_peer)
        if peer_ip:
            for key_name in (
                as_str(self_peer.get("HostName")),
                as_str(self_peer.get("DNSName")),
                as_str(self_peer.get("Name")),
            ):
                for candidate in _name_candidates(key_name):
                    lookup.setdefault(candidate, peer_ip)

    peers = status.get("Peer")
    if isinstance(peers, dict):
        for peer in peers.values():
            if not isinstance(peer, dict):
                continue
            peer_ip = _extract_tailscale_ip(peer)
            if not peer_ip:
                continue
            for key_name in (
                as_str(peer.get("HostName")),
                as_str(peer.get("DNSName")),
                as_str(peer.get("Name")),
            ):
                for candidate in _name_candidates(key_name):
                    lookup.setdefault(candidate, peer_ip)

    return lookup


def _read_tailscale_status(*, command: str = "tailscale") -> dict[str, Any]:
    require_command(command)
    result = subprocess.run(
        [command, "status", "--json"],
        check=True,
        text=True,
        capture_output=True,
    )
    try:
        payload = json.loads(result.stdout)
    except Exception as exc:
        raise RuntimeError(f"failed to parse tailscale status JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("tailscale status JSON response is not an object")
    return payload


def _resolve_tailscale_ip(*, node_name: str, lookup: dict[str, str]) -> str | None:
    for candidate in _name_candidates(node_name):
        ip = lookup.get(candidate)
        if ip:
            return ip
    return None


def _collect_address_lines(
    *,
    services_df: pd.DataFrame,
    tailscale_lookup: dict[str, str],
    caddy_node: str,
    debug: bool,
) -> list[dict[str, str]]:
    line_to_services: dict[str, set[str]] = {}

    for idx, row in services_df.iterrows():
        ingress = _normalize_name(as_str(row.get("ingress")))
        exposure = _normalize_name(as_str(row.get("exposure")))
        if exposure != "trusted":
            continue

        frontend_hostname = _normalize_name(as_str(row.get("frontend_hostname")))
        if not frontend_hostname:
            if debug:
                print(f"[dnsmasq debug] row {idx}: missing frontend_hostname; skipping", file=sys.stderr)
            continue

        if ingress == "caddy":
            target_node = caddy_node
        elif ingress == "direct":
            target_node = _normalize_name(as_str(row.get("hostname")))
        else:
            continue

        if not target_node:
            if debug:
                print(
                    f"[dnsmasq debug] row {idx}: ingress={ingress} but target node is empty; skipping",
                    file=sys.stderr,
                )
            continue

        target_ip = _resolve_tailscale_ip(node_name=target_node, lookup=tailscale_lookup)
        if not target_ip:
            print(
                (
                    f"Warning: row {idx}: no tailscale ip for node={target_node} "
                    f"(service={frontend_hostname}); skipping"
                ),
                file=sys.stderr,
            )
            continue

        line = f"address=/{frontend_hostname}/{target_ip}"
        service_name = as_str(row.get("service_name")) or frontend_hostname
        line_to_services.setdefault(line, set()).add(service_name)

    rendered_lines: list[dict[str, str]] = []
    for line in sorted(line_to_services.keys(), key=str.lower):
        service_names = sorted(line_to_services[line], key=str.lower)
        rendered_lines.append({"line": line, "service_name": ", ".join(service_names)})
    return rendered_lines


def deploy_dnsmasq_addresses_mux(
    *,
    local_path: str,
    host: str,
    username: str,
    remote_path: str,
    restart_command: str,
    port: int | None,
) -> None:
    require_command("scp")
    require_command("ssh")

    target = f"{username}@{host}"
    effective_port = port or 22
    control_path = ssh_control_path(prefix="dnsmasq", username=username, host=host, port=effective_port)

    ssh_args = ssh_base_args(control_path=control_path, port=effective_port, identity_file=None)
    scp_args_list = scp_base_args(control_path=control_path, port=effective_port, identity_file=None)

    ssh_start_master(ssh_args=ssh_args, target=target, env=None)
    try:
        logger.debug("dnsmasq: scp -> %s:%s", target, remote_path)
        subprocess.run([*scp_args_list, local_path, f"{target}:{remote_path}"], check=True)

        logger.debug("dnsmasq: restart -> %s", restart_command)
        ssh_run(ssh_args=ssh_args, target=target, command=restart_command, env=None)
    finally:
        ssh_stop_master(ssh_args=ssh_args, target=target, env=None)


def build_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    tool_dir = Path(__file__).resolve().parent / "dnsmasq"
    config_path, config = pre_parse_config(argv)
    globals_cfg = get_effective_table(config, "globals", legacy_root_fallback=True)
    cfg = get_effective_table(config, "dnsmasq")

    parser = argparse.ArgumentParser(
        description=(
            "Generate dnsmasq config from the Services sheet. Produces trusted service address entries "
            "using Tailscale IPs from 'tailscale status --json'."
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
        "--template",
        type=Path,
        default=Path(get_config_value(cfg, "template", str(tool_dir / "addresses.conf.j2"))),
        help="Path to dnsmasq Jinja2 template",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(get_config_value(cfg, "output", str(tool_dir / "addresses.conf"))),
        help="Path to write rendered dnsmasq config",
    )
    parser.add_argument(
        "--caddy-node",
        default=str(get_config_value(cfg, "caddy_node", get_config_value(globals_cfg, "caddy_hostname", ""))),
        help=(
            "Node name used for ingress=caddy trusted services when resolving Tailscale IP. "
            "Defaults to [dnsmasq].caddy_node then [globals].caddy_hostname."
        ),
    )
    parser.add_argument(
        "--tailscale-command",
        default=str(get_config_value(cfg, "tailscale_command", "tailscale")),
        help="Command name/path for tailscale CLI",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=bool(get_config_value(cfg, "debug", False)),
        help="Enable verbose debug output",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "If set, copy rendered config to /etc/dnsmasq.d/addresses.conf on the Caddy node "
            "and restart dnsmasq over SSH."
        ),
    )
    parser.add_argument(
        "--caddy-host",
        default=None,
        help="SSH hostname/IP for the Caddy node (overrides config and caddy node name)",
    )
    parser.add_argument(
        "--caddy-username",
        default=None,
        help="SSH username for the Caddy node (overrides config)",
    )
    parser.add_argument(
        "--caddy-port",
        default=None,
        help="SSH port for the Caddy node (overrides config)",
    )
    parser.add_argument(
        "--dnsmasq-path",
        default=None,
        help="Remote destination path for dnsmasq addresses file (overrides config)",
    )
    parser.add_argument(
        "--dnsmasq-restart",
        default=None,
        help="Command to restart dnsmasq on Caddy node (overrides config)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(argv)
    args = parser.parse_args(argv)

    config_path = args.config.expanduser().resolve()
    template_path = resolve_path_relative_to_config(config_path, args.template)
    output_path = resolve_path_relative_to_config(config_path, args.output)

    if not template_path.exists():
        print(f"Error: template not found: {template_path}", file=sys.stderr)
        return 2

    if template_path == output_path:
        print(
            "Error: --output resolves to the same path as --template; refusing to overwrite the template.",
            file=sys.stderr,
        )
        return 2

    caddy_node = _normalize_name(str(args.caddy_node))
    if not caddy_node:
        print(
            "Error: caddy node is required (set [dnsmasq].caddy_node, [globals].caddy_hostname, or pass --caddy-node)",
            file=sys.stderr,
        )
        return 2

    if int(args.services_gid) <= 0:
        print("Error: services_gid must be a positive integer", file=sys.stderr)
        return 2

    services_url = build_sheet_url(str(args.sheet_url), int(args.services_gid))

    try:
        services_df = pd.read_csv(services_url)
        services_df = df_with_normalized_columns(services_df)
    except Exception as exc:
        print(f"Error: failed to load services sheet: {exc}", file=sys.stderr)
        return 1

    try:
        tailscale_status = _read_tailscale_status(command=str(args.tailscale_command))
        tailscale_lookup = _build_tailscale_lookup(tailscale_status)
        if not tailscale_lookup:
            raise RuntimeError("tailscale status did not contain any peer/self IP mappings")

        caddy_tailscale_ip = _resolve_tailscale_ip(node_name=caddy_node, lookup=tailscale_lookup)
        if not caddy_tailscale_ip:
            raise RuntimeError(f"no tailscale ip for caddy node '{caddy_node}'")

        address_lines = _collect_address_lines(
            services_df=services_df,
            tailscale_lookup=tailscale_lookup,
            caddy_node=caddy_node,
            debug=bool(args.debug),
        )

        rendered = render_jinja_template(
            template_path=template_path,
            context={
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z"),
                "caddy_tailscale_ip": caddy_tailscale_ip,
                "address_lines": address_lines,
                "address_line_count": len(address_lines),
            },
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        if stderr:
            print(f"Error: tailscale status failed: {stderr}", file=sys.stderr)
        else:
            print("Error: tailscale status failed", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"Rendered {output_path} from template {template_path}")
    print(f"Generated {len(address_lines)} trusted dnsmasq address lines")

    config = load_toml_or_exit(config_path)
    cfg = get_effective_table(config, "dnsmasq")
    deploy_cfg = cfg.get("dnsmasq_deploy", {})
    if not isinstance(deploy_cfg, dict):
        deploy_cfg = {}

    host = args.caddy_host or deploy_cfg.get("host") or caddy_node
    username = args.caddy_username or deploy_cfg.get("username", "root")
    remote_path = args.dnsmasq_path or deploy_cfg.get("path", "/etc/dnsmasq.d/addresses.conf")
    restart_command = (
        args.dnsmasq_restart
        or deploy_cfg.get("restart_command", "sudo systemctl restart dnsmasq")
    )
    port_value = args.caddy_port or deploy_cfg.get("port")

    port = None
    if port_value is not None:
        try:
            port = int(port_value)
        except (TypeError, ValueError):
            print("Error: caddy port must be an integer", file=sys.stderr)
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
                "Error: dnsmasq deploy settings (host, username, path, restart_command) are required.",
                file=sys.stderr,
            )
            return 2
        try:
            deploy_dnsmasq_addresses_mux(
                local_path=str(output_path),
                host=str(host),
                username=str(username),
                remote_path=str(remote_path),
                restart_command=str(restart_command),
                port=port,
            )
        except Exception as exc:
            print(f"Error: dnsmasq apply failed: {exc}", file=sys.stderr)
            return 1
        print(f"Applied dnsmasq addresses to {username}@{host}:{remote_path}")
        print("Restarted dnsmasq on Caddy node")
    else:
        print("Dry run (no --apply): no remote changes made")
        print(f"- generated: {output_path}")
        if missing_deploy:
            print(
                "- would apply: skipped (missing deploy settings: " + ", ".join(missing_deploy) + ")"
            )
        else:
            target = f"{username}@{host}"
            effective_port = port or 22
            print(f"- would scp: {output_path} -> {target}:{remote_path} (port {effective_port})")
            print(f"- would ssh: {target}: {restart_command}")
        print("Re-run with --apply to perform these actions.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
