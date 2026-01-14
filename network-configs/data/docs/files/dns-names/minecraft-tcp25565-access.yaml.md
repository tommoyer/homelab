# dns-names/minecraft-tcp25565-access.yaml
## Purpose
Defines one or more DNS names/records to publish internally and/or externally, targeting either an asset or a service.
## Contents
- schema_version: `1`
- kind: `dns_names`
- object_count: `1`

## Objects
- `minecraft-tcp25565-access`

## Field Documentation
This section documents every field path observed in this file. Field meanings are best-effort and derived from usage across the repository.

| Field | Type | Required (repo)? | Required (file)? | Examples | Description | Notes |
|---|---|---|---|---|---|---|
| `dns_names` | `list` | `n/a` | `n/a` | `list(len=1)` | List of DNS names to publish. |  |
| `dns_names[]` | `list_item`, `object` | `yes` | `yes` | `list(len=1)`, `object(keys=7)` | One DNS name/record definition object within the `dns_names` list. |  |
| `dns_names[].cloudflare` | `object` | `no` | `yes` | `object(keys=2)` | Undocumented field (observed in repo). |  |
| `dns_names[].cloudflare.proxy_status` | `string` | `no` | `yes` | `dns-only` | Undocumented field (observed in repo). |  |
| `dns_names[].cloudflare.target_ip` | `string` | `no` | `yes` | `207.144.81.217` | Undocumented field (observed in repo). |  |
| `dns_names[].dns_id` | `string` | `yes` | `yes` | `minecraft-tcp25565-access` | Stable identifier for the DNS record object. |  |
| `dns_names[].external` | `object` | `yes` | `yes` | `object(keys=5)` | External/public DNS publication config. |  |
| `dns_names[].external.enabled` | `boolean` | `yes` | `yes` | `true` | Whether to publish this record externally. |  |
| `dns_names[].external.provider` | `string` | `no` | `yes` | `cloudflare` | Undocumented field (observed in repo). |  |
| `dns_names[].external.proxied` | `boolean` | `no` | `yes` | `false` | Undocumented field (observed in repo). |  |
| `dns_names[].external.record_type` | `string` | `no` | `yes` | `A` | Undocumented field (observed in repo). |  |
| `dns_names[].external.target` | `string` | `no` | `yes` | `cloudflare_target_ip` | Undocumented field (observed in repo). |  |
| `dns_names[].fqdn` | `string` | `yes` | `yes` | `minecraft.moyer.wtf` | Fully qualified domain name to publish. |  |
| `dns_names[].internal` | `object` | `yes` | `yes` | `object(keys=5)` | Internal DNS publication config (e.g., to Pi-hole). |  |
| `dns_names[].internal.address` | `string` | `yes` | `yes` | `service_backend_ip` | How to compute the record target address. |  |
| `dns_names[].internal.enabled` | `boolean` | `yes` | `yes` | `true` | Whether to publish this record internally. |  |
| `dns_names[].internal.provider` | `string` | `yes` | `yes` | `inherit_vlan` | Internal DNS provider selection; inherit_vlan means use the VLAN’s configured/default provider. |  |
| `dns_names[].internal.publish_scopes` | `list` | `yes` | `yes` | `list(len=1)` | Where to publish this internal record. |  |
| `dns_names[].internal.publish_scopes[]` | `list_item`, `string` | `yes` | `yes` | `list(len=1)`, `self` | Publish scope entry. | Best-effort: 'self' means the record is published within its own VLAN; 'user_vlan_if_enabled' publishes into the user VLAN if enabled globally. |
| `dns_names[].internal.record_type` | `string` | `yes` | `yes` | `A` | DNS record type (observed: A). |  |
| `dns_names[].kind` | `string` | `yes` | `yes` | `access` | Record kind: infra (internal naming) or access (user-facing name). |  |
| `dns_names[].targets` | `object` | `yes` | `yes` | `object(keys=2)` | What this DNS name points to: either an asset or a service. |  |
| `dns_names[].targets.asset_id` | `null` | `yes` | `yes` | `null` | Asset target (mutually exclusive with service_id). |  |
| `dns_names[].targets.service_id` | `string` | `yes` | `yes` | `minecraft-tcp25565` | Service target (mutually exclusive with asset_id). |  |
| `schema_version` | `integer` | `n/a` | `n/a` | `1` | Schema version for this YAML document. |  |


## Related

- Schema reference: [../schema.md](../schema.md)
