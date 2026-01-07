# Network Source of Truth (YAML)

This repository is a Git-native “source of truth” for:
- Inventory (assets/devices)
- Services (things that listen on ports and/or need names)
- Internal DNS (Pi-hole and/or Mikrotik)
- External DNS (Cloudflare)
- Mikrotik firewall/NAT intent
- Future policy layers (Kid Control)

The goal is to avoid a single denormalized spreadsheet where one row simultaneously implies:
- a device record
- a service record
- internal DNS records
- Cloudflare records
- firewall pinholes
- NAT forwards

Instead:
- `assets.yaml` defines devices/hosts
- `services.yaml` defines network-facing services
- `dns_names.yaml` defines internal and external DNS names
- `vlans.yaml` defines VLAN-level defaults (DNS server, “user VLAN”, etc.)
- policy YAMLs define higher-level behaviors (Kid Control, scheduled access, etc.)

This structure makes it easier to:
- keep fields small and purpose-specific
- compose derived configs (Pi-hole, Mikrotik, Cloudflare) from a stable schema
- write small scripts per integration target
- test changes with `--dry-run`
- add new functionality without reworking a monolithic sheet/script

---

## Directory Layout

- `data/`
  - `assets.yaml`
  - `services.yaml`
  - `dns_names.yaml`
  - `vlans.yaml` (optional but recommended)
  - `policies/`
    - `kid_control.yaml` (future)

- `netops/`
  - `netops_lib.py` (shared logic)
  - `apply_pihole.py`
  - `apply_mikrotik_dns.py`
  - `apply_mikrotik_fw_nat.py`
  - `apply_cloudflare_dnscontrol.py`
  - `update_caddyfile_map.py`

---

## Conventions

### IDs
IDs should be stable and “slug-like” (lowercase, hyphens, no spaces). They are used as references between files.

- `assets[].asset_id`
- `services[].service_id`
- `dns_names[].dns_id`

### VLAN IDs
`vlan_id` is the stable logical label for a VLAN. It should match whatever you used historically as the “Subdomain” key (recommended), or a VLAN name.

Examples:
- `homelab`
- `shady`
- `iot`
- `guest`

---

## File: data/assets.yaml

### Top-level
- `schema_version` (int)

### Assets (`assets[]`)
- `asset_id` (string): stable asset identifier.
- `hostname` (string): friendly name.
- `type` (string): classification (e.g. `physical`, `vm`, `container`, `rpi`, `iot`, etc.)
- `owner` (string, optional): owner/user.
- `notes` (string, optional): free-form notes.
- `interfaces[]` (list): one or more network interfaces.

### Interfaces (`assets[].interfaces[]`)
- `if_id` (string): stable interface ID (often equals `vlan_id`).
- `vlan_id` (string): VLAN membership label.
- `ip` (string, optional): interface IP or `dynamic`.
- `mac` (string, optional): MAC address.
- `dns_provider` (enum, optional): `pihole` or `mikrotik` (rare; most logic is vlan-driven).

### Example

```yaml
schema_version: 1
assets:
  - asset_id: "multicast-relay"
    hostname: "multicast-relay"
    type: "vm"
    interfaces:
      - if_id: "homelab"
        vlan_id: "homelab"
        ip: "192.168.10.28"
      - if_id: "shady"
        vlan_id: "shady"
        ip: "192.168.30.2"
```

---

## File: data/services.yaml

### Top-level
- `schema_version` (int)

### Services (`services[]`)
- `service_id` (string): stable identifier.
- `name` (string): friendly name.
- `asset_id` (string): where this service runs.
- `vlan_id` (string): VLAN context for resolution/publishing decisions.
- `backend.ip` (string, optional): explicit backend IP. If omitted, derived from the asset interface for `vlan_id`.
- `backend.port` (int, optional): explicit backend port. If omitted, derived from `ports.service_ports[0]`.
- `ports.service_ports[]` (list): ports used for internal routing / reverse-proxy mapping.
- `ports.firewall_ports[]` (list): ports that should be opened/forwarded externally (dstnat).
- `routing.internal_dns_target` (string, optional): internal DNS routing target (e.g. Caddy IP).
- `routing.via_caddy` (bool): derived/intent flag (true when internal routing is via Caddy).

### Example

```yaml
schema_version: 1
services:
  - service_id: "grafana-tcp3000"
    name: "Grafana"
    asset_id: "pve-grafana-ct"
    vlan_id: "homelab"
    backend:
      ip: "192.168.10.50"
      port: 3000
    ports:
      service_ports:
        - port: 3000
          proto: tcp
      firewall_ports: []
    routing:
      internal_dns_target: "192.168.20.3"
      via_caddy: true
```

---

## File: data/dns_names.yaml

### Top-level
- `schema_version` (int)

### DNS name entries (`dns_names[]`)
- `dns_id` (string): stable identifier.
- `kind` (enum): `infra`, `access`, or `alias`.
- `fqdn` (string): fully qualified domain name.
- `targets.service_id` (string|null): reference to a service if the name is for a service.
- `targets.asset_id` (string|null): reference to an asset if the name is for a device.

#### Internal DNS (`internal.*`)
- `internal.enabled` (bool): publish internally.
- `internal.provider` (enum): `inherit_vlan`, `pihole`, `mikrotik`.
- `internal.record_type` (enum): `A` or `CNAME` (default: `A`).

If `internal.record_type: A`:
- `internal.address` (enum):
  - `asset_ip` (use the asset IP; if multi-interface, uses the “best” IP unless `asset_interface_ip` is used)
  - `asset_interface_ip` (use a specific asset interface IP; requires `internal.interface_id`)
  - `service_backend_ip` (use service backend IP; falls back to asset IP when not set)
  - `routing_internal_dns_target` (use `service.routing.internal_dns_target`)
- `internal.interface_id` (string, optional): interface selector when `internal.address: asset_interface_ip`.
- `internal.publish_scopes` (list):
  - `self` publishes in the VLAN implied by the target/service
  - `user_vlan_if_enabled` publishes to `vlans.yaml:globals.user_vlan` when `globals.access_publish_to_user_vlan` is true

If `internal.record_type: CNAME`:
- `internal.cname_target` (string): canonical target name the alias should point to.
- `internal.publish_scopes` (list): same behavior as for `A`.

#### External DNS (`external.*`)
- `external.enabled` (bool): publish in Cloudflare.
- `external.provider` (enum): currently `cloudflare`.
- `external.record_type` (enum): typically `A` (future: `CNAME`, `AAAA`).
- `external.target` (enum): typically `cloudflare_target_ip` (or future: `public_ip`, `cname`, etc.)
- `external.proxied` (bool): Cloudflare proxy on/off.
- `cloudflare.target_ip` (string): the target IP (if external.enabled).
- `cloudflare.proxy_status` (enum): `proxied` or `dns-only`.

### Example: internal CNAME

```yaml
dns_names:
  - dns_id: "grafana-alias"
    kind: "alias"
    fqdn: "grafana.home.arpa"
    targets:
      service_id: "grafana-tcp3000"
      asset_id: null
    internal:
      enabled: true
      provider: "pihole"
      record_type: "CNAME"
      cname_target: "grafana.internal.home.arpa"
      publish_scopes: ["self"]
    external:
      enabled: false
```

### Example: internal A pinned to a specific interface

```yaml
dns_names:
  - dns_id: "multicast-relay-shady"
    kind: "infra"
    fqdn: "multicast-relay.shady.moyer.wtf"
    targets:
      service_id: null
      asset_id: "multicast-relay"
    internal:
      enabled: true
      provider: "mikrotik"
      record_type: "A"
      address: "asset_interface_ip"
      interface_id: "shady"
      publish_scopes: ["self"]
    external:
      enabled: false
```

---

## File: data/policies/kid_control.yaml

### Top-level
- `schema_version` (int)

### Globals (`globals.*`)
- `globals.timezone` (string): timezone for schedules.
- `globals.user_vlan` (string): a “user” VLAN where certain access names may be published.
- `globals.access_publish_to_user_vlan` (bool): enable publishing certain access names to the user VLAN.
- `globals.caddy_ip` (string): reverse proxy IP used for internal routing logic.

### Kid Control (`kid_control.*`)
- `kid_control.enabled` (bool): enable/disable the policy application.
- `kid_control.default_action` (enum): what to do for devices that match a selector.
- `kid_control.selectors[]`: reusable match definitions (by MAC, IP, tags, etc.)
- `kid_control.rules[]`: time-based policy rules.
- `kid_control.rules[].selector_id` (string): which selector the rule targets.
- `kid_control.rules[].schedule`: schedule definition.
- `kid_control.rules[].action`: block/allow/limit behavior.

---

## File: data/vlans.yaml (optional)

This file defines VLAN-level defaults and server resolution information. It is optional, but recommended when you have multiple Pi-hole instances and/or multiple DNS providers.

### Top-level
- `schema_version` (int)

### Globals (`globals.*`)
- `globals.user_vlan` (string): VLAN ID for user devices.
- `globals.access_publish_to_user_vlan` (bool): when true, certain access names publish to the user VLAN.
- `globals.caddy_ip` (string): reverse proxy IP used for internal routing logic.

### VLAN entries (`vlans[]`)
- `vlan_id` (string): VLAN identifier.
- `dns.default_provider` (enum): `pihole` or `mikrotik`.
- `servers.dns_type` (enum): `pihole` or `mikrotik`.
- `servers.dns_host` (string): hostname/IP for the DNS server for this VLAN.
- `servers.ssh_user` (string): SSH user used to connect.
- `servers.ssh_port` (int): SSH port.
- `servers.use_sudo` (bool): whether to use sudo for Pi-hole file updates.

### Example

```yaml
schema_version: 1
globals:
  user_vlan: "home"
  access_publish_to_user_vlan: true
  caddy_ip: "192.168.20.3"

vlans:
  - vlan_id: "homelab"
    dns:
      default_provider: "pihole"
    servers:
      dns_type: "pihole"
      dns_host: "pihole-homelab.lan"
      ssh_user: "pi"
      ssh_port: 22
      use_sudo: true

  - vlan_id: "shady"
    dns:
      default_provider: "mikrotik"
    servers:
      dns_type: "mikrotik"
      dns_host: "mikrotik-router.lan"
      ssh_user: "admin"
      ssh_port: 22
```

---

## Applying Configurations

The intent is to use small scripts that operate on a single target:

- `netops/apply_pihole.py`: update Pi-hole internal DNS (`pihole.toml`)
- `netops/apply_mikrotik_dns.py`: update Mikrotik static DNS
- `netops/apply_mikrotik_fw_nat.py`: update Mikrotik firewall/NAT rules
- `netops/apply_cloudflare_dnscontrol.py`: update Cloudflare via DNSControl
- `netops/update_caddyfile_map.py`: update Caddyfile map entries

Scripts should support:
- `--dry-run` to generate output without applying changes
- targeted filters like `--vlan` (when applicable)

Recommended orchestration:
- use a `Taskfile.yaml` to run each step independently or as `task all`.

---

## Notes

- Pi-hole file management assumes SSH access to the Pi-hole host and the ability to write `/etc/pihole/pihole.toml`.
- Mikrotik scripts generally apply changes by importing generated `.rsc` scripts, removing previously-generated entries by comment marker, and adding the desired state.
- Cloudflare updates use DNSControl and require `CLOUDFLARE_API_TOKEN`.
