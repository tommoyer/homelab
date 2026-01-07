#!/usr/bin/env python3
"""
apply_mikrotik_fw_nat.py

Generates & applies Mikrotik firewall pinholes (Caddy -> backend) and NAT dstnat rules.

Inputs (from services.yaml):
  - services[].ports.service_ports     => pinholes if service routes via caddy_ip
  - services[].ports.firewall_ports    => public NAT forwards
  - services[].routing.internal_dns_target:
        - if equals caddy_ip: indicates reverse-proxy path (pinholes)
        - if set and firewall_ports present: NAT target IP

Also generates forward filter accept rules for NAT ports (matching your monolith).

Dry-run writes scripts under ./dry-run/
"""

from __future__ import annotations

import argparse
import datetime
import os
from typing import Any, Dict, List, Tuple

from netops_lib import (
    check_prerequisites,
    deploy_mikrotik_script,
    load_config_toml,
    load_sot,
    normalize_ports,
    prompt_password_once,
    service_backend_ip,
)

PLACE_BEFORE_DEFAULT = "Drop invalid/inter-VLAN forward"


def split_ports_by_proto(port_list: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    tcp = []
    udp = []
    for p in port_list:
        proto = str(p.get("proto") or "tcp").lower()
        port = str(p.get("port"))
        if proto == "udp":
            udp.append(port)
        else:
            tcp.append(port)
    return tcp, udp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--config", default="dns-config.toml")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--vlan", action="append", help="Limit to VLAN(s). Can be repeated.")
    ap.add_argument("--caddy-ip", help="Reverse proxy IP (fallback to vlans.yaml globals.caddy_ip, then config caddy_ip)")
    ap.add_argument("--wan-interface", default=None, help="WAN interface name (fallback config wan_interface or ether1)")
    ap.add_argument("--place-before-comment", default=PLACE_BEFORE_DEFAULT)
    ap.add_argument("--router-host")
    ap.add_argument("--router-user")
    ap.add_argument("--router-port")
    ap.add_argument("--router-password")
    ap.add_argument("--skip-firewall", action="store_true")
    args = ap.parse_args()

    if not check_prerequisites(needs_dnscontrol=False):
        return 1

    sot = load_sot(args.data_dir)
    cfg, _ = load_config_toml(args.config)

    # Resolve caddy_ip: CLI > vlans.yaml globals > config
    caddy_ip = args.caddy_ip
    if not caddy_ip:
        vl = sot.get("vlans_doc") or {}
        globals_ = (vl.get("globals") or {}) if isinstance(vl, dict) else {}
        caddy_ip = globals_.get("caddy_ip") or cfg.get("caddy_ip")
    if not caddy_ip:
        print("[Warning] caddy_ip not provided; Caddy pinhole rules will be skipped.")

    wan_interface = args.wan_interface or cfg.get("wan_interface", "ether1")

    router_host = args.router_host or cfg.get("router_host")
    router_user = args.router_user or cfg.get("router_user") or "admin"
    router_port = str(args.router_port or cfg.get("router_port", 22))
    password = args.router_password or cfg.get("router_password")

    if not router_host:
        print("[Error] router_host not set (use --router-host or config router_host).")
        return 2

    if args.dry_run:
        os.makedirs("dry-run", exist_ok=True)

    vlan_filter = {v.lower() for v in args.vlan} if args.vlan else None

    # Build per-vlan rule groups
    assets_by_id = sot["assets_by_id"]
    per_vlan = {}  # vlan_id -> dict of lists: pinholes, nat, nat_fw

    for svc in sot["services"]:
        if not isinstance(svc, dict):
            continue
        vlan_id = str(svc.get("vlan_id") or "").lower()
        if not vlan_id:
            continue
        if vlan_filter and vlan_id not in vlan_filter:
            continue

        ports = svc.get("ports") or {}
        if not isinstance(ports, dict):
            ports = {}

        service_ports = normalize_ports(ports.get("service_ports"))
        firewall_ports = normalize_ports(ports.get("firewall_ports"))

        routing = svc.get("routing") or {}
        if not isinstance(routing, dict):
            routing = {}
        internal_target = routing.get("internal_dns_target")

        backend_ip = service_backend_ip(svc, assets_by_id)
        if not backend_ip:
            continue

        # Pinhole rules: only when caddy_ip is defined and internal_dns_target == caddy_ip
        if not args.skip_firewall and caddy_ip and internal_target and str(internal_target).strip() == str(caddy_ip).strip():
            if service_ports:
                per_vlan.setdefault(vlan_id, {"pinhole": [], "nat": [], "nat_fw": []})
                per_vlan[vlan_id]["pinhole"].append({"dst_ip": backend_ip, "ports": service_ports})

        # NAT rules: require firewall_ports + internal_target (dstnat to internal_target)
        if firewall_ports and internal_target:
            per_vlan.setdefault(vlan_id, {"pinhole": [], "nat": [], "nat_fw": []})
            per_vlan[vlan_id]["nat"].append({"target_ip": str(internal_target).strip(), "ports": firewall_ports})
            per_vlan[vlan_id]["nat_fw"].append({"target_ip": str(internal_target).strip(), "ports": firewall_ports})

    if not per_vlan:
        print("No Mikrotik firewall/NAT rules to apply.")
        return 0

    who = f"{router_user}@{router_host}"
    password = prompt_password_once(password, who=who, dry_run=args.dry_run)

    for vlan_id, bucket in per_vlan.items():
        # 1) Firewall (pinhole + nat forward accept)
        if not args.skip_firewall:
            fw_comment = f"Generated by netops (FW: {vlan_id})"
            fw_filename = f"mikrotik-{vlan_id}-firewall.rsc"
            if args.dry_run:
                fw_filename = os.path.join("dry-run", fw_filename)

            fw_lines = [
                f"# Generated on {datetime.datetime.now()}",
                f':put "Starting Firewall update for VLAN: {vlan_id}"',
                f'/ip firewall filter remove [find comment="{fw_comment}"]',
                ':put "Updating Firewall Rules..."',
            ]

            # A) Caddy pinholes
            if caddy_ip and bucket["pinhole"]:
                fw_lines.append(':put "  Processing Caddy Pinholes..."')
                for r in bucket["pinhole"]:
                    dst_ip = r["dst_ip"]
                    if str(dst_ip).strip() == str(caddy_ip).strip():
                        continue
                    tcp_ports, udp_ports = split_ports_by_proto(r["ports"])
                    if tcp_ports:
                        fw_lines.append(
                            "/ip firewall filter add chain=forward action=accept "
                            f"src-address={caddy_ip} dst-address={dst_ip} "
                            f"protocol=tcp dst-port={','.join(tcp_ports)} "
                            f'place-before=[find comment="{args.place_before_comment}"] '
                            f'comment="{fw_comment}"'
                        )
                    if udp_ports:
                        fw_lines.append(
                            "/ip firewall filter add chain=forward action=accept "
                            f"src-address={caddy_ip} dst-address={dst_ip} "
                            f"protocol=udp dst-port={','.join(udp_ports)} "
                            f'place-before=[find comment="{args.place_before_comment}"] '
                            f'comment="{fw_comment}"'
                        )

            # B) NAT forward accept rules
            if bucket["nat_fw"]:
                fw_lines.append(':put "  Processing NAT Forwarding Rules..."')
                for r in bucket["nat_fw"]:
                    target_ip = r["target_ip"]
                    tcp_ports, udp_ports = split_ports_by_proto(r["ports"])
                    if tcp_ports:
                        fw_lines.append(
                            "/ip firewall filter add chain=forward action=accept "
                            f"dst-address={target_ip} protocol=tcp dst-port={','.join(tcp_ports)} "
                            f'place-before=[find comment="{args.place_before_comment}"] '
                            f'comment="{fw_comment}"'
                        )
                    if udp_ports:
                        fw_lines.append(
                            "/ip firewall filter add chain=forward action=accept "
                            f"dst-address={target_ip} protocol=udp dst-port={','.join(udp_ports)} "
                            f'place-before=[find comment="{args.place_before_comment}"] '
                            f'comment="{fw_comment}"'
                        )

            print(f"Updating Mikrotik Firewall for VLAN {vlan_id} on {router_host}...")
            deploy_mikrotik_script(
                fw_filename,
                fw_lines,
                host=router_host,
                user=router_user,
                port=router_port,
                password=password,
                dry_run=args.dry_run,
                keep_files=args.keep,
            )

        # 2) NAT (dstnat)
        if bucket["nat"]:
            nat_comment = f"Generated by netops (NAT: {vlan_id})"
            nat_filename = f"mikrotik-{vlan_id}-nat.rsc"
            if args.dry_run:
                nat_filename = os.path.join("dry-run", nat_filename)

            nat_lines = [
                f"# Generated on {datetime.datetime.now()}",
                f':put "Starting NAT update for VLAN: {vlan_id}"',
                f'/ip firewall nat remove [find comment="{nat_comment}"]',
                ':put "Updating NAT rules..."',
            ]

            seen = set()
            for r in bucket["nat"]:
                target_ip = r["target_ip"]
                for p in r["ports"]:
                    key = (target_ip, p["port"], p["proto"])
                    if key in seen:
                        continue
                    seen.add(key)
                    nat_lines.append(
                        "/ip firewall nat add chain=dstnat action=dst-nat "
                        f"to-addresses={target_ip} to-ports={p['port']} "
                        f"protocol={p['proto']} dst-port={p['port']} "
                        f"in-interface={wan_interface} "
                        f'comment="{nat_comment}"'
                    )

            print(f"Updating Mikrotik NAT for VLAN {vlan_id} on {router_host}...")
            deploy_mikrotik_script(
                nat_filename,
                nat_lines,
                host=router_host,
                user=router_user,
                port=router_port,
                password=password,
                dry_run=args.dry_run,
                keep_files=args.keep,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
