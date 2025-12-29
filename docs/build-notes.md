# Notes on how things are configured

## Proxmox VE

- Installed using [Proxmox VE Official Guide](https://pve.proxmox.com/wiki/Installation)
- Created Ceph cluster using Web GUI
- Added storage backends for ISO images, container templates, and VM disks
- Setup keepalived for HA using these notes: [Proxmox Keepalived Notes](docs/proxmox-keepalived-notes.md)

## `pihole-homelab`

This Pi-hole instance serves the homelab VLAN

- Base OS: Debian 13
- Container/VM: LXC container via Proxmox
- Installed via: [Pi-hole Official Guide](https://docs.pi-hole.net/main/prerequisites/installation/)
- Added `unbound` using the instructions from [Pi-hole Docs - Using Unbound as a Recursive DNS Resolver](https://docs.pi-hole.net/guides/unbound/)
- Hosts file: `pihole-homelab.toml`
- Remote host: `pihole.homelab.moywer.wtf`
- Remote path: `/etc/pihole/pihole.toml`
- SSH user: `root`
- SSH port: `22`
- DNS entries are generated from the System Inventory CSV for the `homelab` VLAN
- The script `update_pihole_hosts.py` is used to update the hosts file and reload Pi-hole
- Firewall ports for proxy:
    - DMZ[Tailscale] -> Homelab VLAN: 80 (HTTP)

## `pihole-dmz`

This Pi-hole instance serves the DMZ VLAN

- Base OS: Debian 13
- Container/VM: LXC container via Proxmox
- Installed via: [Pi-hole Official Guide](https://docs.pi-hole.net/main/prerequisites/installation/)
- Added `unbound` using the instructions from [Pi-hole Docs - Using Unbound as a Recursive DNS Resolver](https://docs.pi-hole.net/guides/unbound/)
- Hosts file: `pihole-dmz.toml`
- Remote host: `pihole.dmz.moywer.wtf`
- Remote path: `/etc/pihole/pihole.toml`
- SSH user: `root`
- SSH port: `22`
- DNS entries are generated from the System Inventory CSV for the `dmz` VLAN
- The script `update_pihole_hosts.py` is used to update the hosts file and reload Pi-hole
- Firewall ports for proxy:
    - None, same VLAN

## `multicast-relay`

This service relays multicast traffic between VLANs to support mDNS discovery across the network

- Base OS: Debian 13
- Container/VM: LXC container via Proxmox
- Installed via: [Github repository](https://github.com/alsmith/multicast-relay)
- Tweaks/updates: Check issues in the repository for any custom tweaks or updates made
- Firewall ports for proxy:
    - DMZ[Tailscale] -> Homelab VLAN: 80 (HTTP)

## `homarr`

The Homarr dashboard for managing and monitoring services

- Installed via [Proxmox Helper Script for Homarr](https://community-scripts.github.io/ProxmoxVE/scripts?id=homarr)
- Configuration managed in the `homarr` folder of this repository

## `proxy`

The Caddy reverse proxy serving services in the Homelab VLAN from the DMZ VLAN

- Installed via [Proxmox Helper Script for Docker LXC](https://community-scripts.github.io/ProxmoxVE/scripts?id=docker&category=Containers+%26+Docker)
- Dockerfile and configuration managed in the `proxy` folder of this repository

## `ts-router`

The Tailscale Subnet Router providing access to the Homelab VLAN from the DMZ VLAN

- Base OS: Debian 13
- Container/VM: LXC container via Proxmox
- Added Tailscale via [Proxmox Helper Script for Tailscale](https://community-scripts.github.io/ProxmoxVE/scripts?id=add-tailscale-lxc)
- Dockerfile and configuration managed in the `ts-router` folder of this repository