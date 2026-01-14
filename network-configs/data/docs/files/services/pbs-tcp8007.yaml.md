# services/pbs-tcp8007.yaml
## Purpose
Defines one or more network services running on assets, including ports and routing behavior (e.g., via Caddy).
## Contents
- schema_version: `1`
- kind: `services`
- object_count: `1`

## Objects
- `pbs-tcp8007`

## Field Documentation
This section documents every field path observed in this file. Field meanings are best-effort and derived from usage across the repository.

| Field | Type | Required (repo)? | Required (file)? | Examples | Description | Notes |
|---|---|---|---|---|---|---|
| `schema_version` | `integer` | `n/a` | `n/a` | `1` | Schema version for this YAML document. |  |
| `services` | `list` | `n/a` | `n/a` | `list(len=1)` | List of services (network endpoints) running on assets. |  |
| `services[]` | `list_item`, `object` | `yes` | `yes` | `list(len=1)`, `object(keys=8)` | One service definition object within the `services` list. |  |
| `services[].asset_id` | `string` | `yes` | `yes` | `pbs` | Asset where this service runs. |  |
| `services[].backend` | `object` | `yes` | `yes` | `object(keys=2)` | Backend connection details. |  |
| `services[].backend.ip` | `null` | `yes` | `yes` | `null` | Override backend IP (null means derive from asset interface). |  |
| `services[].backend.port` | `integer` | `yes` | `yes` | `8007` | Backend port clients should connect to (often matches service_ports[].port). |  |
| `services[].interface_id` | `string` | `yes` | `yes` | `homelab` | Which interface on the asset should be used for backend addressing. |  |
| `services[].name` | `string` | `yes` | `yes` | `Proxmox Backup Server` | Human-friendly service name. |  |
| `services[].ports` | `object` | `yes` | `yes` | `object(keys=2)` | Port definitions for the service. |  |
| `services[].ports.firewall_ports` | `list` | `yes` | `yes` | `list(len=2)` | Ports that should be exposed via firewall/reverse proxy (commonly 80/443 when using Caddy). |  |
| `services[].ports.firewall_ports[]` | `list_item`, `object` | `yes` | `yes` | `list(len=2)`, `object(keys=2)` | One `firewall_port` entry (port/protocol tuple). |  |
| `services[].ports.firewall_ports[].port` | `integer` | `no` | `yes` | `80`, `443` | Firewall-exposed port. |  |
| `services[].ports.firewall_ports[].proto` | `string` | `no` | `yes` | `tcp` | Firewall-exposed protocol. |  |
| `services[].ports.service_ports` | `list` | `yes` | `yes` | `list(len=1)` | Ports the service listens on (authoritative). |  |
| `services[].ports.service_ports[]` | `list_item`, `object` | `yes` | `yes` | `list(len=1)`, `object(keys=2)` | One `service_port` entry (port/protocol tuple). |  |
| `services[].ports.service_ports[].port` | `integer` | `yes` | `yes` | `8007` | TCP/UDP port. |  |
| `services[].ports.service_ports[].proto` | `string` | `yes` | `yes` | `tcp` | Transport protocol. |  |
| `services[].routing` | `object` | `yes` | `yes` | `object(keys=2)` | How clients should reach the service. |  |
| `services[].routing.internal_dns_target` | `string` | `no` | `yes` | `192.168.20.3` | When routing via Caddy, the internal A record target (often Caddy’s IP). | Only present when via_caddy=true in observed files. |
| `services[].routing.via_caddy` | `boolean` | `yes` | `yes` | `true` | If true, service is routed via Caddy; DNS access names typically point at internal_dns_target. |  |
| `services[].service_id` | `string` | `yes` | `yes` | `pbs-tcp8007` | Stable identifier for the service; often includes port/protocol. |  |
| `services[].vlan_id` | `string` | `yes` | `yes` | `homelab` | VLAN where the service is considered to live. |  |


## Related

- Schema reference: [../schema.md](../schema.md)
