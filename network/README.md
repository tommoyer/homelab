# Network Automation

This directory contains small automation scripts for homelab networking, split into sub-folders based on the service they target:

- `dns/`: NetBox DNS → Cloudflare (dnscontrol)
- `caddy/`: NetBox Services → generated Caddyfile (optionally deployed over SSH)
- `mikrotik/`: RouterOS/MikroTik automation + NetBox Security plugin sync

## Common requirements

- Python 3.10+
- Packages from `requirements.txt`
- `NETBOX_API_KEY` environment variable (required by all scripts that read NetBox)

## `dns/` (NetBox DNS → Cloudflare)

Generates `external_records.json` for dnscontrol from NetBox DNS records.

**Environment variables**

- `NETBOX_API_KEY`: NetBox API token.
- `CLOUDFLARE_API_TOKEN`: Cloudflare API token used by dnscontrol.

**Files**

- Script: `dns/update-dns.py`
- Config: `dns/config.toml` (default for the script)
- dnscontrol support files:
  - `dns/creds.json` (if present, the script prefers writing `external_records.json` alongside it)
  - `dns/dnsconfig.js` (dnscontrol config loader)

**Outputs**

- `<work_dir>/netbox-dns-records.json`: Raw NetBox DNS records payload.
- `external_records.json`: Cloudflare records for dnscontrol.
  - By default this is written next to `dns/creds.json` when it exists, otherwise into `<work_dir>`.

**Usage**

```bash
cd dns

# Generate files (and preview if dnscontrol-dir is configured)
./update-dns.py

# Preview/push via dnscontrol (uses dns/ as dnscontrol dir by default when creds.json exists)
./update-dns.py --apply
```

If you keep your dnscontrol project elsewhere, pass `--dnscontrol-dir /path/to/dnscontrol` (or set `dnscontrol_dir` in `dns/config.toml`).

## `caddy/` (NetBox Services → Caddyfile)

Generates a Caddyfile using NetBox IPAM Services that are marked as being behind the proxy.

**Files**

- Script: `caddy/update-caddy.py`
- Config: `caddy/config.toml`
- Template: `caddy/Caddyfile.template`

**Outputs**

- `<work_dir>/netbox-services.json`: Raw NetBox services payload.
- `<work_dir>/Caddyfile`: Rendered Caddyfile.

**Usage**

```bash
cd caddy

# Generate Caddyfile
./update-caddy.py

# Upload + restart (uses [caddy_deploy] from caddy/config.toml unless overridden)
./update-caddy.py --apply
```

Note: the generated Caddyfile template references `{env.CLOUDFLARE_API_TOKEN}` for the Cloudflare DNS challenge.

## `mikrotik/` (RouterOS + NetBox security sync)

Contains RouterOS-focused scripts and NetBox Security plugin sync tooling:

- `mikrotik/update-firewall.py`
- `mikrotik/update-nat.py`
- `mikrotik/ipam-to-security.py`
- `mikrotik/ipam-to-security-v2.py`

Start here:

- `mikrotik/QUICK-START.md`
- `mikrotik/MIGRATION-GUIDE.md`
- `mikrotik/UPDATE-SUMMARY.md`
