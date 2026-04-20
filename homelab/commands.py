from __future__ import annotations

from . import caddyfile, deploy, dns, mikrotik_prompt, subnet_assign, tailscale_install

# Central registry of homelab CLI commands.
#
# Each entry is:
#   name -> (description, module)
#
# The "run" pseudo-command is handled specially by homelab.cli and does not
# correspond to a single module.
COMMANDS: dict[str, tuple[str, object]] = {
    "run": ("Run multiple features", object()),
    "dns": ("Generate/apply public and internal DNS records", dns),
    "mikrotik": ("Prompt-driven MikroTik command generator (single or batch)", mikrotik_prompt),
    "caddy": ("Generate/deploy Caddyfile from Google Sheets", caddyfile),
    "deploy": ("Deploy a complete node/service", deploy),
    "tailscale_install": ("Install Tailscale from Nodes sheet methods", tailscale_install),
    "subnet_assign": ("Interactive subnet/IP assignment tool", subnet_assign),
}
