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

## `proxy`

The Caddy reverse proxy serving services in the Homelab VLAN from the DMZ VLAN

- Installed via [Proxmox Helper Script for Docker LXC](https://community-scripts.github.io/ProxmoxVE/scripts?id=docker&category=Containers+%26+Docker)
- Dockerfile and configuration managed in the `proxy` folder of this repository

## `unifi`

The UniFi Network Controller managing the UniFi network devices

- Installed via [Proxmox Helper Script for UniFi Controller](https://community-scripts.github.io/ProxmoxVE/scripts?id=unifi)

## `tandoor`

The Tandoor Recipes application for managing recipes and meal planning

- Installed via [Proxmox Helper Script for Tandoor Recipes](https://community-scripts.github.io/ProxmoxVE/scripts?id=tandoor)

## `uptime-kuma`

The Uptime Kuma application for monitoring the uptime of services

- Installed via [Proxmox Helper Script for Uptime Kuma](https://community-scripts.github.io/ProxmoxVE/scripts?id=uptimekuma)

## `firefly-iii`

The Firefly III application for personal finance management

- Installed via [Proxmox Helper Script for Firefly III](https://community-scripts.github.io/ProxmoxVE/scripts?id=firefly)

## `jellyfin`

The Jellyfin media server for streaming media content

- Installed via [Proxmox Helper Script for Jellyfin](https://community-scripts.github.io/ProxmoxVE/scripts?id=jellyfin)

## `syncthing`

Syncthing for file synchronization across devices

- Installed via [Proxmox Helper Script for Syncthing](https://community-scripts.github.io/ProxmoxVE/scripts?id=syncthing)

## `gitea`

Gitea for self-hosted Git repository management

- Installed via [Proxmox Helper Script for Gitea](https://community-scripts.github.io/ProxmoxVE/scripts?id=gitea)

## `vaultwarden`

Vaultwarden for self-hosted password management

- Installed via [Proxmox Helper Script for Vaultwarden](https://community-scripts.github.io/ProxmoxVE/scripts?id=vaultwarden)

## `Grafana`

The Grafana application for data visualization and monitoring

- Installed via [Proxmox Helper Script for Grafana](https://community-scripts.github.io/ProxmoxVE/scripts?id=grafana)

## `tiny-tiny-rss`

The Tiny Tiny RSS application for RSS feed management

- Installed via [Proxmox Helper Script for Docker LXC](https://community-scripts.github.io/ProxmoxVE/scripts?id=docker&category=Containers+%26+Docker)
- Dockerfile and configuration managed in the `tt-rss` folder of this repository

## `smtp-relay`

The SMTP relay service for relaying emails from the homelab

- Base OS: Debian 13
- Container/VM: LXC container via Proxmox

