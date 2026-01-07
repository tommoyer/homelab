# Homelab Configuration

This repository contains configuration files, automation scripts, and documentation for my homelab infrastructure.

## Structure

### [Network Configs](./network-configs)
Scripts and configuration for managing network services, including:
- **DNS Control**: Managing DNS records via code.
- **Pi-hole**: Automation for updating Pi-hole host lists from inventory.
- **Mikrotik**: Generation of RouterOS configuration scripts.

### [Proxy](./proxy)
Reverse proxy configuration using Caddy.
- Custom Caddy build with Cloudflare DNS plugin for DNS-01 challenges.
- Docker Compose setup for easy deployment.

### [Docs](./docs)
General documentation and build notes for various services and setups, including:
- Proxmox and Keepalived notes.
- Tailscale subnet router configuration.

### [WWW](./www)
Static web content and assets.

### [Homepage](./homepage)
Configuration for the gethomepage dashboard, including bookmarks, widgets, and service definitions with custom styling and scripts.

### [TT-RSS](./tt-rss)
Docker Compose stack for Tiny Tiny RSS with a Postgres backend, nginx frontend, and updater/backup jobs managed via env-file configuration.

### [TW-Sync](./tw-sync)
Taskwarrior/Timewarrior sync experiments and notes, including the timew-webhook service for remotely starting and stopping Timewarrior via HTTP (Docker Compose and Swarm ready).

## Getting Started

Please refer to the `README.md` files in each subdirectory for specific setup and usage instructions.
