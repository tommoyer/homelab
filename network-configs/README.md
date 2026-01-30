# NetBox DNS → Cloudflare (dnscontrol)

This folder contains `update-dns.py`, which pulls DNS records from the NetBox DNS plugin and generates the files dnscontrol needs to update Cloudflare.

## Requirements

- Python 3.10+
- NetBox with the DNS plugin enabled
- `NETBOX_API_KEY` environment variable
- dnscontrol installed (only required if you run preview/push)
- Cloudflare API token (used by dnscontrol)

## Environment variables

- `NETBOX_API_KEY`: NetBox API token for reading DNS records.
- `CLOUDFLARE_API_TOKEN`: Cloudflare API token used by dnscontrol.

## dnscontrol credentials file

dnscontrol reads Cloudflare credentials from a `creds.json` file in the dnscontrol directory. Create a file named `creds.json` in the same directory as your dnscontrol config with the following contents:

```json
{
  "cloudflare": {
    "TYPE": "CLOUDFLAREAPI",
    "apitoken": "$CLOUDFLARE_API_TOKEN",
    "accountid": "your-cloudflare-account-id-or-email"
  },
  "none": { "TYPE": "NONE" }
}
```

The `apitoken` value is read from the `CLOUDFLARE_API_TOKEN` environment variable.

## dnsconfig.js setup

`dnsconfig.js` is static and lives in your dnscontrol directory. `update-dns.py` only writes `external_records.json`, which `dnsconfig.js` loads at runtime.

If you keep dnscontrol files in a separate directory, pass `--dnscontrol-dir` or configure `dnscontrol_dir` in `config.toml` so `external_records.json` is written into that same directory.

## Config

The script reads `config.toml` in this directory by default. Key settings:

- `base_url`: NetBox base URL.
- `work_dir`: Where output files are written (defaults to `./downloads`).
- `netbox_dns_endpoint`: Optional override for the NetBox DNS plugin API endpoint.
- `netbox_zone_filters`: Zones/views to include for Cloudflare.
- `dnscontrol_dir`: Directory containing dnscontrol config (optional).
- `dnscontrol_bin`: dnscontrol binary name/path (optional).
- `dnscontrol_records_path`: Optional override for external_records.json output.

Example `netbox_zone_filters`:

```toml
netbox_zone_filters = [
  { zone = "example.com", views = ["external"] },
  { zone = "lab.example.com", views = ["external", "public"] },
]
```

## Outputs

When run, the script writes:

- `downloads/netbox-dns-records.json`: Raw DNS records fetched from NetBox.
- `downloads/external_records.json`: Cloudflare records for dnscontrol.

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
