# NetBox Services → Caddyfile

This folder contains `update-caddy.py`, which pulls IPAM Services from NetBox and generates a Caddyfile.

It’s intended for services that are marked as being behind the reverse proxy (via custom fields on the Service record).

## Requirements

- Python 3.10+
- NetBox IPAM Services API enabled
- `NETBOX_API_KEY` environment variable

## Environment variables

- `NETBOX_API_KEY`: NetBox API token for reading services.
- `CLOUDFLARE_API_TOKEN`: Used by Caddy at runtime for the Cloudflare DNS challenge (referenced in `Caddyfile.template`).

## Config

By default, the script reads `config.toml` in this directory.

Common settings:

- `base_url`: NetBox base URL.
- `work_dir`: Where output files are written (defaults to `./downloads`).
- `caddy_zones`: List of zones to generate server blocks for.
  - `zone` (required)
  - `wildcard` (optional, default `true`)
  - `redirect_www` (optional, default `false`)
- `netbox_zone_filters`: Fallback zone list (only used if `caddy_zones` is not present/valid). Only the `zone` field is used.

### Deployment (`--apply`)

If you run with `--apply`, the script uses `[caddy_deploy]`:

- `host`
- `username`
- `port` (optional)
- `path` (remote Caddyfile path)
- `restart_command` (executed over SSH)

## Files

- `Caddyfile.template`: Template used to render the output.
- `config.toml`: Local config.

## Outputs

- `<work_dir>/netbox-services.json`: Raw services payload fetched from NetBox.
- `<work_dir>/Caddyfile`: Generated Caddyfile.

## Usage

Generate Caddyfile only:

```bash
./update-caddy.py
```

Generate, upload, and restart Caddy:

```bash
./update-caddy.py --apply
```
