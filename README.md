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

## Getting Started

Please refer to the `README.md` files in each subdirectory for specific setup and usage instructions.
