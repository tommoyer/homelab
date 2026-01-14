# Network Config YAML (data/)

This folder contains declarative network inventory and naming configuration. Files are grouped by intent:

- `vlans.yaml`: VLAN definitions and global defaults

- `assets/`: device/host inventory (one file per asset today, but can be many)

- `services/`: services/endpoints running on assets (one file per service today, but can be many)

- `dns-names/`: DNS records to publish (one file per record today, but can be many)


## How things link together

- An `asset_id` identifies a device/host.

- A `service_id` identifies a network service running on an asset (`services[].asset_id`).

- A `dns_id` identifies a DNS record which targets either a `service_id` or an `asset_id`.

- `vlan_id` values tie assets/services/records back to a VLAN definition in `vlans.yaml`.


## Generated documentation

- Index of all YAML file docs: [index.md](index.md)

- Schema reference: [schema.md](schema.md)

