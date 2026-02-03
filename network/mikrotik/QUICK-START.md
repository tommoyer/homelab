# Quick Start: Using the Updated Script

## File Overview

- `ipam-to-security-v2.py` - Updated script with managed tags + automation_key support
- `config-v2.toml` - Updated configuration with `managed_tags_all` and `address_sets`
- `MIGRATION-GUIDE.md` - Detailed step-by-step migration instructions
- `UPDATE-SUMMARY.md` - Quick comparison of v1 vs v2 changes

## Prerequisites

1. **NetBox Tags Created:**
   - `managed-by-script`
   - `scope-hexs`
   - Your existing intent tags: `pathvia-caddy`, `svcbind`, `svcpihole`, `svcminecraft`, `svcmumble`, `monping`, `monhttp`

2. **Custom Fields Created:**
   - `automation_key` on IPAM IP Address
   - `automation_key` on IPAM Service
   - `automation_key` on Security Address
   - `automation_key` on Security Address Set
   - `ipam_backref` on Security Address (should already exist)
   - `ipam_backref` on Security Address Set (should already exist)

3. **Data Tagged:**
   - IP addresses have: `managed-by-script`, `scope-hexs`
   - Services have: `managed-by-script`, `scope-hexs`, + intent tag (e.g., `svcminecraft`)
   - Services are bound to their IP addresses

## Common Commands

### 1. Dry Run (See What Would Happen)
```bash
export NETBOX_API_KEY="your-token-here"

python3 ipam-to-security-v2.py \
  --config config-v2.toml \
  --debug
```

**Output:** Shows which objects would be synced, no changes made.

---

### 2. Dry Run with Payload Details
```bash
python3 ipam-to-security-v2.py \
  --config config-v2.toml \
  --debug \
  --show-payload
```

**Output:** Shows exact JSON payloads that would be sent to NetBox API.

---

### 3. Create New Objects (First Run)
```bash
python3 ipam-to-security-v2.py \
  --config config-v2.toml \
  --apply
```

**Output:** Creates Security Addresses and Address Sets from IPAM data.

---

### 4. Update Existing Objects
```bash
python3 ipam-to-security-v2.py \
  --config config-v2.toml \
  --apply \
  --update
```

**Output:** Updates existing Security objects when source IPAM data changes.

---

### 5. Full Debug Output with HTTP Requests
```bash
python3 ipam-to-security-v2.py \
  --config config-v2.toml \
  --apply \
  --update \
  --debug \
  --show-http-request
```

**Output:** Maximum verbosity - shows every API call, headers, payloads. Use for troubleshooting.

---

### 6. Automated Cron Job (Production)
```bash
# Add to crontab
# Run every 15 minutes, log to syslog
*/15 * * * * cd /opt/scripts && export NETBOX_API_KEY="$(cat /opt/secrets/netbox-api-key)" && python3 ipam-to-security-v2.py --config config-v2.toml --apply --update 2>&1 | logger -t ipam-sync
```

---

## Configuration Tweaks

### Change Base Tags
Edit `config-v2.toml`:
```toml
managed_tags_all = ["managed-by-script", "scope-hexs", "source-routeros"]
```

### Add New Address Set
Add to `config-v2.toml`:
```toml
[[ipam_to_security.address_sets]]
intent_tags_any = ["app-nextcloud"]
address_set = "nextcloud-services"
sources = ["services"]
automation_key = "set:nextcloud"
description = "Nextcloud file sharing services"
```

### Multi-Tag Address Set (OR Logic)
```toml
[[ipam_to_security.address_sets]]
intent_tags_any = ["app-caddy", "app-caddy-backend", "pathvia-caddy"]
address_set = "all-caddy-services"
sources = ["services"]
automation_key = "set:caddy-all"
description = "All Caddy-related services (any tag matches)"
```

### Include Devices in Address Set
```toml
[[ipam_to_security.address_sets]]
intent_tags_any = ["infrastructure"]
address_set = "infrastructure-devices"
sources = ["services", "devices"]  # Both services AND devices
automation_key = "set:infrastructure"
description = "Infrastructure services and device IPs"
```

---

## Verification Checklist

After running `--apply`:

1. **Check Security Addresses:**
   ```
   NetBox UI → Security → Addresses
   ```
   - [ ] IP addresses are /32 (IPv4) or /128 (IPv6)
   - [ ] Custom field `ipam_backref` points to IPAM object
   - [ ] Custom field `automation_key` matches source (if set)

2. **Check Security Address Sets:**
   ```
   NetBox UI → Security → Address Sets
   ```
   - [ ] Sets have expected names (from config)
   - [ ] Sets contain expected IP addresses
   - [ ] Custom field `ipam_backref` points to tag
   - [ ] Custom field `automation_key` matches config (if set)

3. **Run Script Again (Idempotent Test):**
   ```bash
   python3 ipam-to-security-v2.py --config config-v2.toml --apply --update
   ```
   - [ ] Output shows: `created=0 updated=0 skipped=N` (or minimal updates)
   - [ ] No unexpected creates or updates

---

## Troubleshooting

### No objects synced
**Problem:** `Address Summary: created=0 updated=0 skipped=0`

**Solution:**
- Verify IP addresses have ALL base tags: `managed-by-script`, `scope-hexs`
- Run with `--debug` to see what's being fetched
- Check tags are actually applied (not just created in NetBox)

### Address Set is empty
**Problem:** Address Set created but contains 0 addresses

**Solution:**
- Verify Service is bound to IP address (IPAM → Services → Edit → IP Addresses)
- Verify IP address has base tags (`managed-by-script`, `scope-hexs`)
- Service needs base tags + intent tag

### Wrong IP format
**Problem:** IP shows as /24 instead of /32

**Solution:**
- Run with `--apply --update` to normalize existing addresses
- All IPs will be converted to /32 (IPv4) or /128 (IPv6)

### Script can't find custom field
**Error:** `KeyError: 'automation_key'`

**Solution:**
- Verify custom field `automation_key` exists in NetBox
- Check it's enabled for correct content types
- Field name is case-sensitive

### Tag not found
**Error:** HTTP 400 or empty results

**Solution:**
- Verify tag slug spelling (e.g., `managed-by-script` not `managed_by_script`)
- Tags must be created in NetBox first (Extras → Tags)
- Check tag is enabled for IP Address/Service/Device content types

---

## Output Examples

### Successful First Run
```
CREATE  caddy.example.com  192.168.20.3/32  ip:caddy
CREATE  minecraft.example.com  192.168.10.10/32  ip:minecraft
CREATE  mumble.example.com  192.168.10.32/32  ip:mumble
CREATE  bind.example.com  192.168.10.31/32  ip:bind
CREATE  pihole.example.com  192.168.20.2/32  ip:pihole
ADDRSET CREATE  caddy-access-services  pathvia-caddy  2
ADDRSET CREATE  bind-server  svcbind  1
ADDRSET CREATE  pihole-services  svcpihole  1
ADDRSET CREATE  minecraft-server  svcminecraft  1
ADDRSET CREATE  mumble-server  svcmumble  1
ADDRSET CREATE  monitor-ping-targets  monping  5
ADDRSET CREATE  monitor-http-targets  monhttp  3
Address Summary: created=5 updated=0 skipped=0
AddressSet Summary: created=7 updated=0 skipped=0
```

### Subsequent Run (Idempotent)
```
SKIP  caddy.example.com  192.168.20.3/32  ip:caddy
SKIP  minecraft.example.com  192.168.10.10/32  ip:minecraft
SKIP  mumble.example.com  192.168.10.32/32  ip:mumble
SKIP  bind.example.com  192.168.10.31/32  ip:bind
SKIP  pihole.example.com  192.168.20.2/32  ip:pihole
ADDRSET SKIP  caddy-access-services  pathvia-caddy  2
ADDRSET SKIP  bind-server  svcbind  1
ADDRSET SKIP  pihole-services  svcpihole  1
ADDRSET SKIP  minecraft-server  svcminecraft  1
ADDRSET SKIP  mumble-server  svcmumble  1
ADDRSET SKIP  monitor-ping-targets  monping  5
ADDRSET SKIP  monitor-http-targets  monhttp  3
Address Summary: created=0 updated=0 skipped=5
AddressSet Summary: created=0 updated=0 skipped=7
```

### Update Run (Changed DNS Name)
```
UPDATE  caddy-new.example.com  192.168.20.3/32  ip:caddy
SKIP  minecraft.example.com  192.168.10.10/32  ip:minecraft
SKIP  mumble.example.com  192.168.10.32/32  ip:mumble
SKIP  bind.example.com  192.168.10.31/32  ip:bind
SKIP  pihole.example.com  192.168.20.2/32  ip:pihole
ADDRSET SKIP  caddy-access-services  pathvia-caddy  2
...
Address Summary: created=0 updated=1 skipped=4
AddressSet Summary: created=0 updated=0 skipped=7
```

---

## Next Steps

1. **Test in staging first** - If you have a test NetBox, use it
2. **Start small** - Tag 1-2 IPs and Services, verify they sync correctly
3. **Expand gradually** - Add more objects once confident
4. **Monitor initially** - Watch first few automated runs
5. **Set up alerting** - Monitor cron job output for errors

---

## Getting Help

If stuck, check:
1. `MIGRATION-GUIDE.md` - Detailed step-by-step instructions
2. `UPDATE-SUMMARY.md` - Comparison of v1 vs v2 changes
3. Run with `--debug --show-payload` for detailed output
4. Check NetBox API logs: Background Tasks → View All
5. Verify custom fields and tags exist and are spelled correctly

## File Permissions

Make script executable:
```bash
chmod +x ipam-to-security-v2.py
```

Store API key securely:
```bash
# Option 1: Environment variable
export NETBOX_API_KEY="your-token"

# Option 2: Secure file
echo "your-token" > /opt/secrets/netbox-api-key
chmod 600 /opt/secrets/netbox-api-key
export NETBOX_API_KEY="$(cat /opt/secrets/netbox-api-key)"
```
