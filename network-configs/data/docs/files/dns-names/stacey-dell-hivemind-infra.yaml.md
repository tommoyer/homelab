# dns-names/stacey-dell-hivemind-infra.yaml
## Purpose
Defines one or more DNS names/records to publish internally and/or externally, targeting either an asset or a service.
## Contents
- schema_version: `1`
- kind: `dns_names`
- object_count: `1`

## Objects
- `stacey-dell-hivemind-infra`

## Field Documentation
This section documents every field path observed in this file. Field meanings are best-effort and derived from usage across the repository.

| Field | Type | Required (repo)? | Required (file)? | Examples | Description | Notes |
|---|---|---|---|---|---|---|
| `dns_names` | `list` | `n/a` | `n/a` | `list(len=1)` | List of DNS names to publish. |  |
| `dns_names[]` | `list_item`, `object` | `yes` | `yes` | `list(len=1)`, `object(keys=6)` | One DNS name/record definition object within the `dns_names` list. |  |
| `dns_names[].dns_id` | `string` | `yes` | `yes` | `stacey-dell-hivemind-infra` | Stable identifier for the DNS record object. |  |
| `dns_names[].external` | `object` | `yes` | `yes` | `object(keys=1)` | External/public DNS publication config. |  |
| `dns_names[].external.enabled` | `boolean` | `yes` | `yes` | `false` | Whether to publish this record externally. |  |
| `dns_names[].fqdn` | `string` | `yes` | `yes` | `stacey-dell.hivemind.moyer.wtf` | Fully qualified domain name to publish. |  |
| `dns_names[].internal` | `object` | `yes` | `yes` | `object(keys=6)` | Internal DNS publication config (e.g., to Pi-hole). |  |
| `dns_names[].internal.address` | `string` | `yes` | `yes` | `asset_interface_ip` | How to compute the record target address. |  |
| `dns_names[].internal.enabled` | `boolean` | `yes` | `yes` | `true` | Whether to publish this record internally. |  |
| `dns_names[].internal.interface_id` | `string` | `no` | `yes` | `hivemind` | When targeting an asset interface, which interface to use. | Only present when address=asset_interface_ip in observed files. |
| `dns_names[].internal.provider` | `string` | `yes` | `yes` | `inherit_vlan` | Internal DNS provider selection; inherit_vlan means use the VLAN’s configured/default provider. |  |
| `dns_names[].internal.publish_scopes` | `list` | `yes` | `yes` | `list(len=1)` | Where to publish this internal record. |  |
| `dns_names[].internal.publish_scopes[]` | `list_item`, `string` | `yes` | `yes` | `list(len=1)`, `self` | Publish scope entry. | Best-effort: 'self' means the record is published within its own VLAN; 'user_vlan_if_enabled' publishes into the user VLAN if enabled globally. |
| `dns_names[].internal.record_type` | `string` | `yes` | `yes` | `A` | DNS record type (observed: A). |  |
| `dns_names[].kind` | `string` | `yes` | `yes` | `infra` | Record kind: infra (internal naming) or access (user-facing name). |  |
| `dns_names[].targets` | `object` | `yes` | `yes` | `object(keys=2)` | What this DNS name points to: either an asset or a service. |  |
| `dns_names[].targets.asset_id` | `string` | `yes` | `yes` | `stacey-dell` | Asset target (mutually exclusive with service_id). |  |
| `dns_names[].targets.service_id` | `null` | `yes` | `yes` | `null` | Service target (mutually exclusive with asset_id). |  |
| `schema_version` | `integer` | `n/a` | `n/a` | `1` | Schema version for this YAML document. |  |


## Related

- Schema reference: [../schema.md](../schema.md)
