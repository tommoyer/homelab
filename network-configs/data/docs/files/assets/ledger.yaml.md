# assets/ledger.yaml
## Purpose
Defines one or more assets (devices/hosts) and their network interfaces. These are referenced by `services` and `dns_names`.
## Contents
- schema_version: `1`
- kind: `assets`
- object_count: `1`

## Objects
- `ledger`

## Field Documentation
This section documents every field path observed in this file. Field meanings are best-effort and derived from usage across the repository.

| Field | Type | Required (repo)? | Required (file)? | Examples | Description | Notes |
|---|---|---|---|---|---|---|
| `assets` | `list` | `n/a` | `n/a` | `list(len=1)` | List of assets (devices/hosts/things) on the network. |  |
| `assets[]` | `list_item`, `object` | `yes` | `yes` | `list(len=1)`, `object(keys=4)` | One asset definition object within the `assets` list. |  |
| `assets[].asset_id` | `string` | `yes` | `yes` | `ledger` | Stable identifier for the asset; used by services and DNS names. |  |
| `assets[].hostname` | `string` | `yes` | `yes` | `ledger` | Hostname for the asset. |  |
| `assets[].interfaces` | `list` | `yes` | `yes` | `list(len=1)` | Network interfaces for the asset. |  |
| `assets[].interfaces[]` | `list_item`, `object` | `yes` | `yes` | `list(len=1)`, `object(keys=4)` | One interface definition object within an asset’s `interfaces` list. |  |
| `assets[].interfaces[].dns_provider` | `string` | `yes` | `yes` | `pihole` | DNS provider for publishing this interface’s records (or where the VLAN inherits provider behavior). |  |
| `assets[].interfaces[].if_id` | `string` | `yes` | `yes` | `homelab` | Stable interface identifier within the asset. |  |
| `assets[].interfaces[].ip` | `string` | `yes` | `yes` | `192.168.10.9` | IP address for the interface or 'dynamic' if DHCP/reserved elsewhere. |  |
| `assets[].interfaces[].vlan_id` | `string` | `yes` | `yes` | `homelab` | VLAN where this interface lives. |  |
| `assets[].type` | `string` | `yes` | `yes` | `unknown` | Asset type (best-effort; often 'unknown'). |  |
| `schema_version` | `integer` | `n/a` | `n/a` | `1` | Schema version for this YAML document. |  |


## Related

- Schema reference: [../schema.md](../schema.md)
