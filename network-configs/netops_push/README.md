# NetOps SOT Push Scripts

This directory contains small Python scripts that take your YAML “source of truth” (SOT) and push derived configuration to:

- Pi-hole v6 (`pihole.toml` local DNS records)
- MikroTik RouterOS (NAT + firewall rules, fully reconciled by comment prefix)
- Caddy reverse proxy (`Caddyfile`, managed sections regenerated)
- Cloudflare DNS via `dnscontrol` (generated include file + `check/preview/push`)

All scripts support:
- `--dry-run` to show what would change (diffs for files, commands for RouterOS, dnscontrol preview)
- `--cache-dir` (default `cache/`) to store downloaded/generated artifacts (git-ignored)
- `--keep` to retain artifacts after successful apply (failures always keep artifacts)

Recommended: add `cache/` to `.gitignore`.

---

## Requirements

- Python 3.11+ recommended
- `pyyaml`:
  ```bash
  pip install pyyaml
  ```

- SSH/SCP access to Pi-hole, MikroTik, and Caddy hosts (key-based login recommended)
- `dnscontrol` installed and usable from your `dnscontrol` directory

---

## Inputs

Each script takes explicit SOT inputs. Each input can be either:
- a single YAML file, or
- a directory containing YAML files (each file is a single YAML document)

Required flags:

- `--assets <path>`
- `--dns-names <path>`
- `--services <path>`
- `--vlans <path>`

Example (directories for some SOT sections):

```bash
--assets sot/assets/ \
--dns-names sot/dns-names/ \
--services sot/services/ \
--vlans sot/vlans.yaml
```

---

## Cache Directory

By default artifacts are written to:

- `cache/pihole/<vlan_id>/...`
- `cache/caddy/...`
- `cache/dnscontrol/...`

Override with `--cache-dir <path>`.

Artifacts are overwritten in place on each run.

---

## Script Overview

### 1) Pi-hole updater

Updates:
- `dns.hosts`
- `dns.cnameRecords`

Workflow:
1. Download `/etc/pihole/pihole.toml`
2. Rewrite only the managed sections
3. Show unified diff in `--dry-run`
4. Upload and run `pihole reloaddns` on apply

Usage (dry-run):

```bash
python -m netops_push.update_pihole \
  --assets sot/assets.yaml \
  --dns-names sot/dns-names/ \
  --services sot/services/ \
  --vlans sot/vlans.yaml \
  --dry-run
```

Usage (apply):

```bash
python -m netops_push.update_pihole \
  --assets sot/assets.yaml \
  --dns-names sot/dns-names/ \
  --services sot/services/ \
  --vlans sot/vlans.yaml
```

Keep artifacts after success:

```bash
python -m netops_push.update_pihole ... --keep
```

Optional: process only one VLAN (debug use):

```bash
python -m netops_push.update_pihole ... --vlan-id homelab
```

---

### 2) MikroTik updater

Reconciliation behavior:
- Deletes all NAT/filter rules that have comments matching the prefix `HOMELAB:SOT`
- Re-adds the desired rules with that prefix
- Adds rules at the top (`place-before=0`) so defaults remain at the bottom

Dry-run prints the RouterOS commands that would be executed.

Usage (dry-run commands):

```bash
python -m netops_push.update_mikrotik \
  --assets sot/assets.yaml \
  --dns-names sot/dns-names/ \
  --services sot/services/ \
  --vlans sot/vlans.yaml \
  --dry-run
```

Usage (apply):

```bash
python -m netops_push.update_mikrotik \
  --assets sot/assets.yaml \
  --dns-names sot/dns-names/ \
  --services sot/services/ \
  --vlans sot/vlans.yaml
```

If the MikroTik SSH target cannot be inferred from `vlans.yaml`, override it:

```bash
python -m netops_push.update_mikrotik \
  --assets ... --dns-names ... --services ... --vlans ... \
  --mikrotik-host 192.168.1.1 \
  --mikrotik-user admin
```

Common knobs:
- `--wan-list-name WAN` (default: `WAN`)
- `--vlan-ifname-template vlan{vlan_tag}` (default: `vlan{vlan_tag}`)

Example if your VLAN interface names are `vlan10-homelab`:

```bash
python -m netops_push.update_mikrotik ... \
  --vlan-ifname-template "vlan{vlan_tag}-{vlan_id}"
```

---

### 3) Caddy updater

Updates the Caddyfile on the reverse-proxy host using SSH/SCP:

1. Download current Caddyfile
2. Generate managed sections (map block + special-case blocks)
3. Show unified diff in `--dry-run`
4. Upload + install
5. Restart using docker compose:
   - `cd <compose_dir> && docker compose restart`

Usage (dry-run diff):

```bash
python -m netops_push.update_caddy \
  --assets sot/assets.yaml \
  --dns-names sot/dns-names/ \
  --services sot/services/ \
  --vlans sot/vlans.yaml \
  --dry-run
```

Usage (apply):

```bash
python -m netops_push.update_caddy \
  --assets sot/assets.yaml \
  --dns-names sot/dns-names/ \
  --services sot/services/ \
  --vlans sot/vlans.yaml
```

#### Required YAML fields for Caddy generation

In `vlans.yaml` (globals):

```yaml
globals:
  caddy_ip: "192.168.20.3"
  caddy:
    ssh_host: "192.168.20.3"
    ssh_user: "ubuntu"
    ssh_port: 22
    use_sudo: true
    caddyfile_path: "/path/to/Caddyfile"
    compose_dir: "/path/to/dir/containing/docker-compose.yml"
```

For each service that has `routing.via_caddy: true`:

```yaml
routing:
  via_caddy: true
  caddy_port: 8006                  # REQUIRED
  tls_insecure_skip_verify: true    # OPTIONAL (default false)
```

If `routing.via_caddy: true` and `caddy_port` is missing, the script fails with an error.

---

### 4) Cloudflare via dnscontrol

Generates a JS include file containing records derived from SOT, then runs:

- `dnscontrol check`
- `dnscontrol preview`
- (and `dnscontrol push` when not `--dry-run`)

Usage (dry-run: check + preview only):

```bash
python -m netops_push.update_cloudflare_dnscontrol \
  --assets sot/assets.yaml \
  --dns-names sot/dns-names/ \
  --services sot/services/ \
  --vlans sot/vlans.yaml \
  --dnscontrol-dir path/to/dnscontrol \
  --zones moyer.wtf thomasmoyer.org \
  --dry-run
```

Usage (apply):

```bash
python -m netops_push.update_cloudflare_dnscontrol \
  --assets sot/assets.yaml \
  --dns-names sot/dns-names/ \
  --services sot/services/ \
  --vlans sot/vlans.yaml \
  --dnscontrol-dir path/to/dnscontrol \
  --zones moyer.wtf thomasmoyer.org
```

Skip `dnscontrol check` (not recommended):

```bash
python -m netops_push.update_cloudflare_dnscontrol ... --no-check
```

Output include file defaults to:

- `cache/dnscontrol/netops_sot_records.js`

Override with:

```bash
python -m netops_push.update_cloudflare_dnscontrol ... \
  --include-path /some/other/path/netops_sot_records.js
```

Your `dnsconfig.js` should `require()` the generated include file and use `NETOPS_SOT_RECORDS["zone"]` for each `D()`.

---

## Push Everything (Fail Fast)

Runs in this order:
1. Pi-hole
2. MikroTik
3. Caddy
4. Cloudflare (dnscontrol)

Dry-run:

```bash
python -m netops_push.push_all \
  --assets sot/assets.yaml \
  --dns-names sot/dns-names/ \
  --services sot/services/ \
  --vlans sot/vlans.yaml \
  --dnscontrol-dir path/to/dnscontrol \
  --zones moyer.wtf thomasmoyer.org \
  --dry-run
```

Apply:

```bash
python -m netops_push.push_all \
  --assets sot/assets.yaml \
  --dns-names sot/dns-names/ \
  --services sot/services/ \
  --vlans sot/vlans.yaml \
  --dnscontrol-dir path/to/dnscontrol \
  --zones moyer.wtf thomasmoyer.org
```

Keep artifacts after success:

```bash
python -m netops_push.push_all ... --keep
```

---

## Troubleshooting

- All scripts keep artifacts on failure automatically. Look under `cache/` to inspect:
  - downloaded originals
  - generated new versions

Pi-hole:
- Verify SSH and sudo permissions for the configured user
- Verify `/etc/pihole/pihole.toml` exists and is writable via `install`

MikroTik:
- Ensure SSH access is enabled and the user has permission to modify firewall/NAT
- Confirm your WAN interface list name matches `--wan-list-name`

Caddy:
- Confirm `compose_dir` contains the docker compose file used to run Caddy
- Confirm the configured `caddyfile_path` is the actual path used by the container

Cloudflare/dnscontrol:
- Ensure your credentials are configured as expected in your dnscontrol setup
- Verify that `dnsconfig.js` requires the generated include file
