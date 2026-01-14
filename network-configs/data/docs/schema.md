# Schema Reference

This is a best-effort reference for fields observed in this repository.

## Notes

- Most files use `schema_version: 1`.

- Lists are documented using `[]` in field paths (e.g., `assets[]`, `assets[].interfaces[]`).

- If a field appears in a file but is not documented here, the per-file doc will label it as 'Undocumented field (observed in repo)'.


## Fields

| Field | Type | Required? | Examples | Description | Notes |
|---|---|---|---|---|---|
| `assets` | `list` | `n/a` | `list(len=1)` | List of assets (devices/hosts/things) on the network. |  |
| `assets[]` | `list_item`, `object` | `yes` | `list(len=1)`, `object(keys=4)` | One asset definition object within the `assets` list. |  |
| `assets[].asset_id` | `string` | `yes` | `capax`, `clean-air-1`, `clean-air-2`, `color-printer`, `cookbook`, `crs-0` | Stable identifier for the asset; used by services and DNS names. |  |
| `assets[].hostname` | `string` | `yes` | `capax`, `clean-air-1`, `clean-air-2`, `color-printer`, `cookbook`, `crs-0` | Hostname for the asset. |  |
| `assets[].interfaces` | `list` | `yes` | `list(len=1)` | Network interfaces for the asset. |  |
| `assets[].interfaces[]` | `list_item`, `object` | `yes` | `list(len=1)`, `object(keys=4)` | One interface definition object within an asset’s `interfaces` list. |  |
| `assets[].interfaces[].dns_provider` | `string` | `yes` | `pihole` | DNS provider for publishing this interface’s records (or where the VLAN inherits provider behavior). |  |
| `assets[].interfaces[].if_id` | `string` | `yes` | `hivemind`, `homelab`, `dmz` | Stable interface identifier within the asset. |  |
| `assets[].interfaces[].ip` | `string` | `yes` | `192.168.1.7`, `dynamic`, `192.168.10.8`, `192.168.1.2`, `192.168.10.6`, `192.168.1.15` | IP address for the interface or 'dynamic' if DHCP/reserved elsewhere. |  |
| `assets[].interfaces[].vlan_id` | `string` | `yes` | `hivemind`, `homelab`, `dmz` | VLAN where this interface lives. |  |
| `assets[].type` | `string` | `yes` | `unknown` | Asset type (best-effort; often 'unknown'). |  |
| `dns_names` | `list` | `n/a` | `list(len=1)` | List of DNS names to publish. |  |
| `dns_names[]` | `list_item`, `object` | `yes` | `list(len=1)`, `object(keys=6)`, `object(keys=7)` | One DNS name/record definition object within the `dns_names` list. |  |
| `dns_names[].cloudflare` | `object` | `no` | `object(keys=2)` | Undocumented field (observed in repo). |  |
| `dns_names[].cloudflare.proxy_status` | `string` | `no` | `proxied`, `dns-only` | Undocumented field (observed in repo). |  |
| `dns_names[].cloudflare.target_ip` | `string` | `no` | `207.144.81.217` | Undocumented field (observed in repo). |  |
| `dns_names[].dns_id` | `string` | `yes` | `capax-hivemind-infra`, `clean-air-1-hivemind-infra`, `clean-air-2-hivemind-infra`, `color-printer-hivemind-infra`, `cookbook-homelab-infra`, `cookbook-tcp8002-access` | Stable identifier for the DNS record object. |  |
| `dns_names[].external` | `object` | `yes` | `object(keys=1)`, `object(keys=5)` | External/public DNS publication config. |  |
| `dns_names[].external.enabled` | `boolean` | `yes` | `false`, `true` | Whether to publish this record externally. |  |
| `dns_names[].external.provider` | `string` | `no` | `cloudflare` | Undocumented field (observed in repo). |  |
| `dns_names[].external.proxied` | `boolean` | `no` | `true`, `false` | Undocumented field (observed in repo). |  |
| `dns_names[].external.record_type` | `string` | `no` | `A` | Undocumented field (observed in repo). |  |
| `dns_names[].external.target` | `string` | `no` | `cloudflare_target_ip` | Undocumented field (observed in repo). |  |
| `dns_names[].fqdn` | `string` | `yes` | `capax.hivemind.moyer.wtf`, `clean-air-1.hivemind.moyer.wtf`, `clean-air-2.hivemind.moyer.wtf`, `color-printer.hivemind.moyer.wtf`, `cookbook.homelab.moyer.wtf`, `cookbook.moyer.wtf` | Fully qualified domain name to publish. |  |
| `dns_names[].internal` | `object` | `yes` | `object(keys=6)`, `object(keys=5)` | Internal DNS publication config (e.g., to Pi-hole). |  |
| `dns_names[].internal.address` | `string` | `yes` | `asset_interface_ip`, `routing_internal_dns_target`, `service_backend_ip` | How to compute the record target address. |  |
| `dns_names[].internal.enabled` | `boolean` | `yes` | `true` | Whether to publish this record internally. |  |
| `dns_names[].internal.interface_id` | `string` | `no` | `hivemind`, `homelab`, `dmz` | When targeting an asset interface, which interface to use. | Only present when address=asset_interface_ip in observed files. |
| `dns_names[].internal.provider` | `string` | `yes` | `inherit_vlan` | Internal DNS provider selection; inherit_vlan means use the VLAN’s configured/default provider. |  |
| `dns_names[].internal.publish_scopes` | `list` | `yes` | `list(len=1)`, `list(len=2)` | Where to publish this internal record. |  |
| `dns_names[].internal.publish_scopes[]` | `list_item`, `string` | `yes` | `list(len=1)`, `self`, `list(len=2)`, `user_vlan_if_enabled` | Publish scope entry. | Best-effort: 'self' means the record is published within its own VLAN; 'user_vlan_if_enabled' publishes into the user VLAN if enabled globally. |
| `dns_names[].internal.record_type` | `string` | `yes` | `A` | DNS record type (observed: A). |  |
| `dns_names[].kind` | `string` | `yes` | `infra`, `access` | Record kind: infra (internal naming) or access (user-facing name). |  |
| `dns_names[].targets` | `object` | `yes` | `object(keys=2)` | What this DNS name points to: either an asset or a service. |  |
| `dns_names[].targets.asset_id` | `null`, `string` | `yes` | `capax`, `clean-air-1`, `clean-air-2`, `color-printer`, `cookbook`, `null` | Asset target (mutually exclusive with service_id). |  |
| `dns_names[].targets.service_id` | `null`, `string` | `yes` | `null`, `cookbook-tcp8002`, `git-ssh-tcp3000`, `git-tcp3000`, `grafana-tcp3000`, `home-tcp3000` | Service target (mutually exclusive with asset_id). |  |
| `globals` | `object` | `n/a` | `object(keys=4)` | Global defaults used when generating/deriving other config (DNS names, access publishing, etc.). |  |
| `globals.access_publish_to_user_vlan` | `boolean` | `n/a` | `true` | If true, access FQDNs may also be published into the user VLAN, depending on per-record publish scopes. |  |
| `globals.base_domain` | `string` | `n/a` | `moyer.wtf` | Base public DNS zone / domain. |  |
| `globals.caddy_ip` | `string` | `n/a` | `192.168.20.3` | IP address of the Caddy reverse proxy (used as an internal DNS target for services routed via Caddy). |  |
| `globals.user_vlan` | `string` | `n/a` | `hivemind` | VLAN id treated as the user-facing VLAN (used by publishing rules). |  |
| `schema_version` | `integer` | `yes` | `1` | Schema version for this YAML document. |  |
| `services` | `list` | `n/a` | `list(len=1)` | List of services (network endpoints) running on assets. |  |
| `services[]` | `list_item`, `object` | `yes` | `list(len=1)`, `object(keys=8)` | One service definition object within the `services` list. |  |
| `services[].asset_id` | `string` | `yes` | `cookbook`, `git-ssh`, `git`, `grafana`, `home`, `kuma` | Asset where this service runs. |  |
| `services[].backend` | `object` | `yes` | `object(keys=2)` | Backend connection details. |  |
| `services[].backend.ip` | `null` | `yes` | `null` | Override backend IP (null means derive from asset interface). |  |
| `services[].backend.port` | `integer` | `yes` | `8002`, `3000`, `3001`, `80`, `8096`, `25565` | Backend port clients should connect to (often matches service_ports[].port). |  |
| `services[].interface_id` | `string` | `yes` | `homelab`, `dmz`, `hivemind` | Which interface on the asset should be used for backend addressing. |  |
| `services[].name` | `string` | `yes` | `Tandoor`, `Gitea (SSH)`, `Gitea`, `Grafana`, `Homepage`, `Uptime Kuma` | Human-friendly service name. |  |
| `services[].ports` | `object` | `yes` | `object(keys=2)` | Port definitions for the service. |  |
| `services[].ports.firewall_ports` | `list` | `yes` | `list(len=2)`, `list(len=1)`, `list(len=0)` | Ports that should be exposed via firewall/reverse proxy (commonly 80/443 when using Caddy). |  |
| `services[].ports.firewall_ports[]` | `list_item`, `object` | `yes` | `list(len=2)`, `object(keys=2)`, `list(len=1)`, `list(len=0)` | One `firewall_port` entry (port/protocol tuple). |  |
| `services[].ports.firewall_ports[].port` | `integer` | `no` | `80`, `443`, `3000`, `22`, `8096`, `25565` | Firewall-exposed port. |  |
| `services[].ports.firewall_ports[].proto` | `string` | `no` | `tcp`, `udp` | Firewall-exposed protocol. |  |
| `services[].ports.service_ports` | `list` | `yes` | `list(len=1)`, `list(len=2)`, `list(len=3)` | Ports the service listens on (authoritative). |  |
| `services[].ports.service_ports[]` | `list_item`, `object` | `yes` | `list(len=1)`, `object(keys=2)`, `list(len=2)`, `list(len=3)` | One `service_port` entry (port/protocol tuple). |  |
| `services[].ports.service_ports[].port` | `integer` | `yes` | `8002`, `3000`, `22`, `3001`, `80`, `8096` | TCP/UDP port. |  |
| `services[].ports.service_ports[].proto` | `string` | `yes` | `tcp`, `udp` | Transport protocol. |  |
| `services[].routing` | `object` | `yes` | `object(keys=2)`, `object(keys=1)` | How clients should reach the service. |  |
| `services[].routing.internal_dns_target` | `string` | `no` | `192.168.20.3`, `192.168.10.13`, `192.168.10.10` | When routing via Caddy, the internal A record target (often Caddy’s IP). | Only present when via_caddy=true in observed files. |
| `services[].routing.via_caddy` | `boolean` | `yes` | `true`, `false` | If true, service is routed via Caddy; DNS access names typically point at internal_dns_target. |  |
| `services[].service_id` | `string` | `yes` | `cookbook-tcp8002`, `git-ssh-tcp3000`, `git-tcp3000`, `grafana-tcp3000`, `home-tcp3000`, `kuma-tcp3001` | Stable identifier for the service; often includes port/protocol. |  |
| `services[].vlan_id` | `string` | `yes` | `homelab`, `dmz`, `hivemind` | VLAN where the service is considered to live. |  |
| `vlans` | `list` | `n/a` | `list(len=4)` | List of VLAN definitions. |  |
| `vlans[]` | `list_item`, `object` | `yes` | `list(len=4)`, `object(keys=6)` | One VLAN definition object within the `vlans` list. |  |
| `vlans[].cidr` | `null`, `string` | `yes` | `192.168.1.0/24`, `192.168.10.0/24`, `192.168.20.0/24`, `null` | IPv4 CIDR for the VLAN (or null if not managed here). |  |
| `vlans[].dns` | `object` | `yes` | `object(keys=2)` | DNS behavior for this VLAN. |  |
| `vlans[].dns.default_provider` | `string` | `yes` | `pihole`, `mikrotik` | Default DNS provider for records in this VLAN (e.g., pihole, mikrotik). |  |
| `vlans[].dns.include_access_fqdn` | `boolean` | `yes` | `true`, `false` | If true, include access FQDNs in this VLAN’s DNS namespace. |  |
| `vlans[].servers` | `object` | `yes` | `object(keys=5)` | Connection details for managing infra services in this VLAN (e.g., Pi-hole host). |  |
| `vlans[].servers.dns_host` | `string` | `yes` | `192.168.1.4`, `192.168.10.27`, `192.168.20.2` | Host/IP used to manage the DNS server for this VLAN. |  |
| `vlans[].servers.dns_type` | `string` | `yes` | `pihole`, `mikrotik` | DNS server type/implementation. |  |
| `vlans[].servers.ssh_port` | `integer` | `yes` | `22` | SSH port. |  |
| `vlans[].servers.ssh_user` | `string` | `yes` | `tom-tom`, `root` | SSH username used for remote management. |  |
| `vlans[].servers.use_sudo` | `boolean` | `yes` | `true`, `false` | Whether management commands should be run with sudo. |  |
| `vlans[].suffixes` | `object` | `yes` | `object(keys=2)` | DNS suffixes used to construct FQDNs. |  |
| `vlans[].suffixes.access` | `string` | `yes` | `moyer.wtf` | Suffix/zone for user-facing/access names. |  |
| `vlans[].suffixes.infra` | `string` | `yes` | `hivemind.moyer.wtf`, `homelab.moyer.wtf`, `dmz.moyer.wtf`, `shady.moyer.wtf` | Suffix/zone for internal infrastructure names for this VLAN. |  |
| `vlans[].vlan_id` | `string` | `yes` | `hivemind`, `homelab`, `dmz`, `shady` | Stable identifier for the VLAN used throughout the repo. |  |
| `vlans[].vlan_tag` | `integer` | `yes` | `1`, `10`, `20`, `30` | 802.1Q VLAN tag number. |  |
