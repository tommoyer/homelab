from __future__ import annotations

import argparse
from pathlib import Path

from .common import SSHSpec, ssh_run_lines
from .sot import COMMENT_PREFIX, load_sot


def _guess_mikrotik_target(sot) -> SSHSpec | None:
    # Prefer any VLAN that declares a mikrotik server with a host.
    for v in sot.vlans.values():
        if v.servers and v.servers.dns_type == "mikrotik" and v.servers.dns_host:
            return SSHSpec(
                host=v.servers.dns_host,
                user=v.servers.ssh_user,
                port=v.servers.ssh_port,
                use_sudo=False,
            )
    return None


def _iface_name(vlan_id: str, vlan_tag: int, template: str) -> str:
    return template.format(vlan_id=vlan_id, vlan_tag=vlan_tag)


def _routeros_escape_comment(s: str) -> str:
    return s.replace('"', '\\"')


def _build_commands(
    sot,
    *,
    wan_list_name: str,
    vlan_if_template: str,
) -> list[str]:
    cmds: list[str] = []

    # Reconcile: delete what we own
    cmds += [
        f'/ip firewall nat remove [find comment~"^{COMMENT_PREFIX}"]',
        f'/ip firewall filter remove [find comment~"^{COMMENT_PREFIX}"]',
        f'/interface list member remove [find comment~"^{COMMENT_PREFIX}"]',
        f'/interface list remove [find comment~"^{COMMENT_PREFIX}"]',
    ]

    # Interface lists per VLAN (optional but requested)
    for v in sorted(sot.vlans.values(), key=lambda x: x.vlan_tag):
        ifname = _iface_name(v.vlan_id, v.vlan_tag, vlan_if_template)
        list_name = f"VLAN_{v.vlan_id}"
        c = _routeros_escape_comment(f"{COMMENT_PREFIX} iface-list {v.vlan_id}")
        cmds.append(f'/interface list add name="{list_name}" comment="{c}"')
        cmds.append(f'/interface list member add list="{list_name}" interface="{ifname}" comment="{c}"')

    # Build port-forwards based on external-enabled DNS names.
    # Assumptions:
    #   - external-enabled => should be reachable from WAN
    #   - if service.routing.via_caddy => forward 80/443 to globals.caddy_ip
    #   - otherwise forward service "firewall_ports" to backend/ip or asset interface ip
    caddy_needed = False

    for dn in sot.dns_names.values():
        if not dn.external.enabled:
            continue
        if not dn.targets.service_id:
            continue

        svc = sot.services[dn.targets.service_id]

        if svc.routing.via_caddy:
            caddy_needed = True
            continue

        # Determine destination IP
        dst_ip = svc.backend.ip
        if not dst_ip:
            asset = sot.assets[svc.asset_id]
            dst_ip = None
            for itf in asset.interfaces:
                if itf.if_id == svc.interface_id:
                    if itf.ip == "dynamic":
                        raise ValueError(f"Service {svc.service_id}: interface IP is dynamic")
                    dst_ip = itf.ip
                    break
            if not dst_ip:
                raise ValueError(f"Service {svc.service_id}: unable to resolve asset interface IP")

        # Prefer firewall_ports for exposure
        ports = svc.ports.firewall_ports or svc.ports.service_ports
        for p in ports:
            to_port = p.backend_port
            if to_port is None:
                if svc.backend.port is not None and len(ports) == 1:
                    to_port = int(svc.backend.port)
                else:
                    to_port = int(p.port)

            comment = _routeros_escape_comment(f"{COMMENT_PREFIX} {svc.service_id} {p.proto} {p.port}->{to_port}")
            cmds.append(
                f"/ip firewall nat add place-before=0 chain=dstnat in-interface-list={wan_list_name} "
                f"protocol={p.proto} dst-port={p.port} action=dst-nat to-addresses={dst_ip} to-ports={to_port} "
                f'comment="{comment}"'
            )
            cmds.append(
                f"/ip firewall filter add place-before=0 chain=forward in-interface-list={wan_list_name} "
                f"connection-nat-state=dstnat protocol={p.proto} dst-port={p.port} dst-address={dst_ip} action=accept "
                f'comment="{comment}"'
            )

    if caddy_needed:
        if not sot.globals.caddy_ip:
            raise ValueError("globals.caddy_ip is required for via_caddy services")
        for port in (80, 443):
            comment = _routeros_escape_comment(f"{COMMENT_PREFIX} caddy tcp {port}->{port}")
            cmds.append(
                f"/ip firewall nat add place-before=0 chain=dstnat in-interface-list={wan_list_name} "
                f"protocol=tcp dst-port={port} action=dst-nat to-addresses={sot.globals.caddy_ip} to-ports={port} "
                f'comment="{comment}"'
            )
            cmds.append(
                f"/ip firewall filter add place-before=0 chain=forward in-interface-list={wan_list_name} "
                f"connection-nat-state=dstnat protocol=tcp dst-port={port} dst-address={sot.globals.caddy_ip} action=accept "
                f'comment="{comment}"'
            )

    return cmds


def main() -> int:
    ap = argparse.ArgumentParser(description="Update Mikrotik NAT + firewall rules from SOT YAML.")
    ap.add_argument("--assets", required=True, type=Path)
    ap.add_argument("--dns-names", required=True, type=Path)
    ap.add_argument("--services", required=True, type=Path)
    ap.add_argument("--vlans", required=True, type=Path)

    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--identity-file", default=None)

    # Target selection: try YAML, else CLI overrides
    ap.add_argument("--mikrotik-host", default=None)
    ap.add_argument("--mikrotik-user", default=None)
    ap.add_argument("--mikrotik-port", type=int, default=22)

    ap.add_argument("--wan-list-name", default="WAN")
    ap.add_argument("--vlan-ifname-template", default="vlan{vlan_tag}", help="Uses {vlan_tag} and {vlan_id}")

    args = ap.parse_args()

    sot = load_sot(
        assets_path=args.assets,
        dns_names_path=args.dns_names,
        services_path=args.services,
        vlans_path=args.vlans,
    )

    spec = None
    if args.mikrotik_host and args.mikrotik_user:
        spec = SSHSpec(
            host=args.mikrotik_host,
            user=args.mikrotik_user,
            port=args.mikrotik_port,
            use_sudo=False,
            identity_file=args.identity_file,
        )
    else:
        guessed = _guess_mikrotik_target(sot)
        if not guessed:
            raise ValueError("Unable to determine Mikrotik SSH target from vlans.yaml; provide --mikrotik-host/--mikrotik-user")
        spec = SSHSpec(
            host=guessed.host,
            user=guessed.user,
            port=guessed.port,
            use_sudo=False,
            identity_file=args.identity_file,
        )

    cmds = _build_commands(
        sot,
        wan_list_name=args.wan_list_name,
        vlan_if_template=args.vlan_ifname_template,
    )

    if args.dry_run:
        for c in cmds:
            print(c)
        return 0

    # Apply: feed commands via stdin
    ssh_run_lines(spec, cmds, capture=True)
    print("Mikrotik rules updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

