from __future__ import annotations

from . import caddyfile, deploy, dnscontrol, mikrotik_prompt, pihole, subnet_assign

# Central registry of homelab CLI commands.
#
# Each entry is:
#   name -> (description, module)
#
# The "run" pseudo-command is handled specially by homelab.cli and does not
# correspond to a single module.
COMMANDS: dict[str, tuple[str, object]] = {
    "run": ("Run multiple features", object()),
    "pihole": ("Generate/apply Pi-hole config", pihole),
    "dnscontrol": ("Generate dnscontrol files for Cloudflare public DNS", dnscontrol),
    "mikrotik": ("Prompt-driven single-service MikroTik command generator", mikrotik_prompt),
    "caddy": ("Generate/deploy Caddyfile from Google Sheets", caddyfile),
    "deploy": ("Deploy a complete node/service", deploy),
    "subnet_assign": ("Interactive subnet/IP assignment tool", subnet_assign),
}
