# vlans.yaml
## Purpose
Defines VLANs and global DNS/routing defaults used to derive other configuration (assets, services, DNS names).
## Contents
- schema_version: `1`
- kind: `vlans`
- object_count: `4`

## Objects
- `hivemind`
- `homelab`
- `dmz`
- `shady`

## Field Documentation
This section documents every field path observed in this file. Field meanings are best-effort and derived from usage across the repository.

| Field | Type | Required (repo)? | Required (file)? | Examples | Description | Notes |
|---|---|---|---|---|---|---|
| `globals` | `object` | `n/a` | `n/a` | `object(keys=4)` | Global defaults used when generating/deriving other config (DNS names, access publishing, etc.). |  |
| `globals.access_publish_to_user_vlan` | `boolean` | `n/a` | `n/a` | `true` | If true, access FQDNs may also be published into the user VLAN, depending on per-record publish scopes. |  |
| `globals.base_domain` | `string` | `n/a` | `n/a` | `moyer.wtf` | Base public DNS zone / domain. |  |
| `globals.caddy_ip` | `string` | `n/a` | `n/a` | `192.168.20.3` | IP address of the Caddy reverse proxy (used as an internal DNS target for services routed via Caddy). |  |
| `globals.user_vlan` | `string` | `n/a` | `n/a` | `hivemind` | VLAN id treated as the user-facing VLAN (used by publishing rules). |  |
| `schema_version` | `integer` | `n/a` | `n/a` | `1` | Schema version for this YAML document. |  |
| `vlans` | `list` | `n/a` | `n/a` | `list(len=4)` | List of VLAN definitions. |  |
| `vlans[]` | `list_item`, `object` | `yes` | `yes` | `list(len=4)`, `object(keys=6)` | One VLAN definition object within the `vlans` list. |  |
| `vlans[].cidr` | `null`, `string` | `yes` | `yes` | `192.168.1.0/24`, `192.168.10.0/24`, `192.168.20.0/24`, `null` | IPv4 CIDR for the VLAN (or null if not managed here). |  |
| `vlans[].dns` | `object` | `yes` | `yes` | `object(keys=2)` | DNS behavior for this VLAN. |  |
| `vlans[].dns.default_provider` | `string` | `yes` | `yes` | `pihole`, `mikrotik` | Default DNS provider for records in this VLAN (e.g., pihole, mikrotik). |  |
| `vlans[].dns.include_access_fqdn` | `boolean` | `yes` | `yes` | `true`, `false` | If true, include access FQDNs in this VLAN’s DNS namespace. |  |
| `vlans[].servers` | `object` | `yes` | `yes` | `object(keys=5)` | Connection details for managing infra services in this VLAN (e.g., Pi-hole host). |  |
| `vlans[].servers.dns_host` | `string` | `yes` | `yes` | `192.168.1.4`, `192.168.10.27`, `192.168.20.2` | Host/IP used to manage the DNS server for this VLAN. |  |
| `vlans[].servers.dns_type` | `string` | `yes` | `yes` | `pihole`, `mikrotik` | DNS server type/implementation. |  |
| `vlans[].servers.ssh_port` | `integer` | `yes` | `yes` | `22` | SSH port. |  |
| `vlans[].servers.ssh_user` | `string` | `yes` | `yes` | `tom-tom`, `root` | SSH username used for remote management. |  |
| `vlans[].servers.use_sudo` | `boolean` | `yes` | `yes` | `true`, `false` | Whether management commands should be run with sudo. |  |
| `vlans[].suffixes` | `object` | `yes` | `yes` | `object(keys=2)` | DNS suffixes used to construct FQDNs. |  |
| `vlans[].suffixes.access` | `string` | `yes` | `yes` | `moyer.wtf` | Suffix/zone for user-facing/access names. |  |
| `vlans[].suffixes.infra` | `string` | `yes` | `yes` | `hivemind.moyer.wtf`, `homelab.moyer.wtf`, `dmz.moyer.wtf`, `shady.moyer.wtf` | Suffix/zone for internal infrastructure names for this VLAN. |  |
| `vlans[].vlan_id` | `string` | `yes` | `yes` | `hivemind`, `homelab`, `dmz`, `shady` | Stable identifier for the VLAN used throughout the repo. |  |
| `vlans[].vlan_tag` | `integer` | `yes` | `yes` | `1`, `10`, `20`, `30` | 802.1Q VLAN tag number. |  |


## Related

- Schema reference: [schema.md](schema.md)
