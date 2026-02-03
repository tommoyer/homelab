# NetBox DNS → Cloudflare (dnscontrol)

This folder contains `update-dns.py`, which pulls DNS records from the NetBox DNS plugin and generates `external_records.json` for dnscontrol (Cloudflare).

## Requirements

- Python 3.10+
- NetBox with the DNS plugin enabled
- `NETBOX_API_KEY` environment variable
- dnscontrol installed (only required if you run preview/push)
- Cloudflare API token (used by dnscontrol)

## Environment variables

- `NETBOX_API_KEY`: NetBox API token for reading DNS records.
- `CLOUDFLARE_API_TOKEN`: Cloudflare API token used by dnscontrol.

## Config

By default, the script reads `config.toml` in this directory.

Common settings:

- `base_url`: NetBox base URL.
- `work_dir`: Where output files are written (defaults to `./downloads`).
- `netbox_dns_endpoint`: Optional override for the NetBox DNS plugin API endpoint.
- `netbox_zone_filters`: Zones/views to include for Cloudflare.
- `dnscontrol_dir`: Directory containing dnscontrol config (optional).
- `dnscontrol_bin`: dnscontrol binary name/path (optional).
- `dnscontrol_records_path`: Optional override for `external_records.json` output.
- `dnscontrol_no_check`: Skip `dnscontrol check` step when running dnscontrol.

Example `netbox_zone_filters`:

```toml
netbox_zone_filters = [
  { zone = "example.com", views = ["external"] },
  { zone = "lab.example.com", views = ["external", "public"] },
]
```

## dnscontrol notes

- If `creds.json` exists in this folder, the script will default `external_records.json` to live alongside it.
- `dnsconfig.js` is static; it loads `external_records.json` at runtime.

## Outputs

When run, the script writes:

- `<work_dir>/netbox-dns-records.json`: Raw DNS records fetched from NetBox.
- `external_records.json`: Cloudflare records for dnscontrol.

## Usage

Preview dnscontrol changes (no push):

```bash
./update-dns.py --dnscontrol-dir /path/to/dnscontrol
```

Apply dnscontrol changes:

```bash
./update-dns.py --dnscontrol-dir /path/to/dnscontrol --apply
```

If you only want to generate files without running dnscontrol, omit `--dnscontrol-dir`.
