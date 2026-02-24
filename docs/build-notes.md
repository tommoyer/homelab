# Notes on how things are configured

## Proxmox VE

- Installed using [Proxmox VE Official Guide](https://pve.proxmox.com/wiki/Installation)
- Created Ceph cluster using Web GUI
- Added storage backends for ISO images, container templates, and VM disks
- Setup keepalived for HA using these notes: [Proxmox Keepalived Notes](docs/proxmox-keepalived-notes.md)

## `pihole`

This Pi-hole instance serves as the internal DNS for the home network

- Installed via [Proxmox Helper Script for Pi-hole](https://community-scripts.github.io/ProxmoxVE/scripts?id=pihole&category=Adblock+%26+DNS)
- Configured to use the Unbound DNS server for upstream DNS resolution
- A and CNAME records generated from the `pihole` folder of this repository using the [Pi-hole DNS Record Generator Script](#)

## `uptime-kuma`

The Uptime Kuma application for monitoring the uptime of services

- Installed via [Docker Compose for Uptime Kuma](https://github.com/louislam/uptime-kuma/blob/master/compose.yaml)
- Installed on Raspberry Pi 4 running Raspberry Pi OS

## `proxy`

The Caddy reverse proxy serving services in the Homelab VLAN from the DMZ VLAN

- Installed via [Proxmox Helper Script for Caddy](https://community-scripts.github.io/ProxmoxVE/scripts?id=caddy)
- Caddyfile generated from the `caddy` folder of this repository using the [Caddyfile Generator Script](#)

# NOT DONE YET

## `homarr`

The Homarr dashboard for managing and monitoring services

- Installed via [Proxmox Helper Script for Homarr](https://community-scripts.github.io/ProxmoxVE/scripts?id=homarr)



## `unifi`

The UniFi Network Controller managing the UniFi network devices

- Installed via [Proxmox Helper Script for UniFi Controller](https://community-scripts.github.io/ProxmoxVE/scripts?id=unifi)

## `tandoor`

The Tandoor Recipes application for managing recipes and meal planning

- Installed via [Proxmox Helper Script for Tandoor Recipes](https://community-scripts.github.io/ProxmoxVE/scripts?id=tandoor)



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

## `grafana`

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

## `ts-router`

The Tailscale router for routing traffic between Tailscale and the homelab VLAN

- Base OS: Debian 13
- Container/VM: LXC container via Proxmox
- Tailscale installed via [Proxmox Helper Script for Tailscale](https://community-scripts.github.io/ProxmoxVE/scripts?id=add-tailscale-lxc&category=Proxmox+%26+Virtualization)
- Configured as a subnet router for the homelab VLAN [notes](https://tailscale.com/kb/1406/quick-guide-subnets)

```
tailscale up --advertise-routes=192.168.1.0/24,192.168.10.0/24,192.168.20.0/24
```

- Approved in the Tailscale admin console

## `pbs`

The Proxmox Backup Server for backing up Proxmox VMs and containers

- Installed via [Proxmox Helper Script for Proxmox Backup Server](https://community-scripts.github.io/ProxmoxVE/scripts?id=proxmox-backup-server)
- Configured intialliy via the [PBS Post Install Script](https://community-scripts.github.io/ProxmoxVE/scripts?id=post-pbs-install&category=Proxmox+%26+Virtualization)

## `gitea-runner`

The Gitea Runner for running CI/CD pipelines from Gitea

- Installed via [Proxmox Helper Script for Docker LXC](https://community-scripts.github.io/ProxmoxVE/scripts?id=docker&category=Containers+%26+Docker)
- Dockerfile and configuration managed in the `gitea-runner` folder of this repository
- Added a DNS record to `/etc/hosts` to resolve `git.moyer.wtf` to the Caddy proxy in the DMZ
- TODO: Should we publish A record for `git.moyer.wtf` in Pihole instead of editing `/etc/hosts`?
- Changed permissions of `/var/run/docker.sock` to `666` to allow the Gitea Runner to access Docker

## `www`

The static website hosted at `thomasmoyer.org`

- Installed via [Proxmox Helper Script for Docker LXC](https://community-scripts.github.io/ProxmoxVE/scripts?id=docker&category=Containers+%26+Docker)
- Dockerfile and configuration managed in the `www` folder of this repository
- Added a DNS record to `/etc/hosts` to resolve `git.moyer.wtf` to the Caddy proxy in the DMZ
- TODO: Should we publish A record for `git.moyer.wtf` in Pihole instead of editing `/etc/hosts`?
- Set GITEA_TOKEN secret in Proxmox LXC container for pushing updates to Gitea

## `mumble`

The Mumble server for voice communication

- Base OS: Debian 13
- Container/VM: LXC container via Proxmox
- Installed from APT repository