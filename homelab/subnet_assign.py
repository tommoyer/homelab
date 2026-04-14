"""
Interactive subnet/IP assignment tool for homelab network

 Reads Google Sheet config from config.toml (with CLI override)
 Uses sheets.py to load and normalize Zones and Nodes tabs
 Presents ncurses menu: <vlan name> : <network>
 On selection, finds next available IP (skipping .1, .255, and assigned IPs)
 Generates random MAC address with prefix BC:24:11
 Prints result to terminal
"""

import argparse
import collections
import curses
import ipaddress
import random
from pathlib import Path

# Import sheets.py helpers
from homelab import sheets
from homelab.config import (
    DEFAULT_SHEET_URL,
    get_config_value,
    get_table,
    pre_parse_config,
)


def build_parser(argv=None):
    config_path, config = pre_parse_config(argv)
    globals_cfg = get_table(config, "globals")
    parser = argparse.ArgumentParser(description="Interactive subnet/IP assignment tool")
    parser.add_argument('--config', type=Path, default=config_path, help='Path to config.toml')
    parser.add_argument(
        '--sheet-url',
        default=get_config_value(globals_cfg, "sheet_url", DEFAULT_SHEET_URL),
        help='Google Sheet URL',
    )
    parser.add_argument(
        '--zones-gid',
        type=int,
        default=int(get_config_value(globals_cfg, "zones_gid", 0)),
        help='Zones tab GID',
    )
    parser.add_argument(
        '--nodes-gid',
        type=int,
        default=int(get_config_value(globals_cfg, "nodes_gid", 0)),
        help='Nodes tab GID',
    )
    return parser


def get_zones(sheet_url, zones_gid):
    df = sheets.get_sheet_df(sheet_url, zones_gid, 30, "Zones")
    zones = []
    for _, row in df.iterrows():
        subnet = sheets.as_str(row.get("network"))
        vlan_name = sheets.as_str(row.get("vlan_name"))
        if subnet and vlan_name:
            zones.append({'subnet': subnet, 'vlan_name': vlan_name})
    return zones


def get_assigned_ips(sheet_url, nodes_gid):
    df = sheets.get_sheet_df(sheet_url, nodes_gid, 30, "Nodes")
    subnet_to_ips = {}
    proxmox_node_counts = collections.Counter()
    for _, row in df.iterrows():
        subnet = sheets.as_str(row.get("subnet"))
        ip = sheets.as_str(row.get("ip_address"))
        proxmox_node = sheets.as_str(row.get("proxmox_node"))
        if subnet and ip:
            subnet_to_ips.setdefault(subnet, set()).add(ip)
        if proxmox_node:
            proxmox_node_counts[proxmox_node] += 1
    return subnet_to_ips, proxmox_node_counts


def suggest_proxmox_node(proxmox_node_counts):
    if not proxmox_node_counts:
        return None
    min_count = min(proxmox_node_counts.values())
    candidates = [node for node, count in proxmox_node_counts.items() if count == min_count]
    return sorted(candidates)[0]


def pick_subnet_menu(zones):
    def menu(stdscr):
        curses.curs_set(0)
        stdscr.clear()
        stdscr.addstr(0, 0, "Select a subnet:")
        for idx, z in enumerate(zones):
            stdscr.addstr(idx+1, 2, f"{z['vlan_name']} : {z['subnet']}")
        selected = 0
        while True:
            for idx, z in enumerate(zones):
                if idx == selected:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(idx+1, 2, f"{z['vlan_name']} : {z['subnet']}")
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(idx+1, 2, f"{z['vlan_name']} : {z['subnet']}")
            key = stdscr.getch()
            if key == curses.KEY_UP and selected > 0:
                selected -= 1
            elif key == curses.KEY_DOWN and selected < len(zones) - 1:
                selected += 1
            elif key in (curses.KEY_ENTER, 10, 13):
                return zones[selected]
    return curses.wrapper(menu)


def find_next_ip(subnet, assigned_ips):
    net = ipaddress.ip_network(subnet)
    skip = {str(net.network_address + 1), str(net.broadcast_address)}
    skip.update(assigned_ips)
    for host in net.hosts():
        ip = str(host)
        if ip.endswith('.1') or ip.endswith('.255'):
            continue
        if ip not in skip:
            return ip
    return None


def random_mac(prefix="BC:24:11"):
    # Generate 3 random bytes
    return prefix + ":" + ":".join(f"{random.randint(0, 255):02X}" for _ in range(3))


def main(argv=None):
    parser = build_parser(argv)
    args = parser.parse_args(argv)
    sheet_url = args.sheet_url
    zones_gid = args.zones_gid
    nodes_gid = args.nodes_gid
    if (sheet_url is None or zones_gid is None or nodes_gid is None):
        print("Missing sheet_url, zones_gid, or nodes_gid. Check config or provide overrides.")
        return 1
    zones = get_zones(sheet_url, zones_gid)
    subnet_to_ips, proxmox_node_counts = get_assigned_ips(sheet_url, nodes_gid)
    selected = pick_subnet_menu(zones)
    subnet = selected['subnet']
    vlan_name = selected['vlan_name']
    assigned = subnet_to_ips.get(subnet, set())
    next_ip = find_next_ip(subnet, assigned)
    suggested_proxmox_node = suggest_proxmox_node(proxmox_node_counts)
    if not next_ip:
        print(f"No available IPs in {subnet}")
        return 1
    mac = random_mac()
    print(f"\nSelected: {vlan_name} : {subnet}")
    print(f"Next available IP: {next_ip}")
    if suggested_proxmox_node:
        print(f"Suggested Proxmox node: {suggested_proxmox_node} (fewest current instances)")
    else:
        print("Suggested Proxmox node: unavailable (no proxmox_node values found)")
    print(f"Random MAC: {mac}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
