# Notes on how things are configured

## Hardware Nodes

### Mikrotik Devices

Single-service RouterOS rule generation is now handled via the unified command:

```
python -m homelab mikrotik
```

- Uses a curses-based form UI to edit one service at a time.
- Prefills fields from `config.toml` and Google Sheets service/node data when available.
- Shows a curses confirmation screen before generating commands.
- Generates RouterOS commands only (no direct apply) and writes an `.rsc` artifact.

Non-interactive mode (sheet as source of truth):

```
python -m homelab mikrotik --no-prompt --service ptero-panel.moyer.wtf
```

- `--no-prompt` requires `--service`.
- In this mode, generation uses Google Sheet values directly (no curses form/confirmation).

- Regular backups for both done using [Oxidized](https://github.com/ytti/oxidized)


### Proxmox VE

- Installed using [Proxmox VE Official Guide](https://pve.proxmox.com/wiki/Installation)
- Created Ceph cluster using Web GUI
- Added storage backends for ISO images, container templates, and VM disks
- Setup keepalived for HA using these notes: [Proxmox Keepalived Notes](docs/proxmox-keepalived-notes.md)

### Pihole

This Pi-hole instance serves as the internal DNS for the hivemind VLAN

- Installed Raspberry Pi OS
- Run Ansible scripts to onboard and then install Pihole
- A and CNAME records generated from the `homelab` folder of this repository using the `pihole` subcommand

### Unifi Dream Router and Unifi U6+ Access Point

Manually configured using the Unifi Network Controller web interface with input from Perplexity

## Virtual Nodes

### Caddy (`caddy.dmz.moyer.wtf`)

The Caddy reverse proxy serving services in the Homelab and Hivemind VLANs from the DMZ VLAN

- Installed via [Proxmox Helper Script for Caddy](https://community-scripts.github.io/ProxmoxVE/scripts?id=caddy)
- Caddyfile generated from the `homelab` folder of this repository using the `caddy` subcommand

# NOT DONE YET

1. Uptime Kuma
2. Homarr
3. Tandoor
4. Firefly III
5. Jellyfin
6. Syncthing
7. Gitea
8. Vaultwarden
9. Tiny Tiny RSS
10. SMTP Relay
11. PBS
12. Gitea Runner
13. WWW
14. Pterodactyl Panel
15. Minecraft
16. Authentik