# Migration Guide: IPAM to Security Script v2

## Overview

This guide walks you through migrating from the current tag-based script to the new version with managed tags, automation keys, and improved address normalization.

## Key Changes in v2

1. **Managed Tags (Safety Fence)**: All objects must have base tags like `managed-by-script` and `scope-hexs`
2. **Automation Keys**: Optional stable identifiers in custom fields for reliable reconciliation
3. **Improved Address Normalization**: All IP addresses converted to /32 (IPv4) or /128 (IPv6)
4. **Intent Tags with OR Logic**: Address sets can match multiple tags
5. **Better Matching**: Finds existing Security objects by backref OR automation_key

## Prerequisites

### 1. Create NetBox Tags

In NetBox UI, navigate to **Extras → Tags** and create:

| Tag Slug | Name | Color | Description |
|----------|------|-------|-------------|
| `managed-by-script` | Managed by Script | Blue | Objects managed by automation scripts |
| `scope-hexs` | Scope: hEX S | Green | Objects in hEX S router scope |
| `source-routeros` | Source: RouterOS | Orange | Data sourced from RouterOS (optional for future) |

Keep your existing intent tags:
- `pathvia-caddy` - Services behind Caddy
- `svcbind` - BIND DNS service
- `svcpihole` - Pi-hole service  
- `svcminecraft` - Minecraft service
- `svcmumble` - Mumble service
- `monping` - Ping monitoring targets
- `monhttp` - HTTP monitoring targets

### 2. Create Custom Fields

#### For IPAM IP Address Objects
Navigate to **Customization → Custom Fields → Add**

**Custom Field 1: automation_key**
- Content Type: `IPAM > IP address`
- Type: Text
- Name: `automation_key`
- Label: `Automation Key`
- Description: `Stable identifier for automation reconciliation`
- Required: No
- Weight: 100

#### For IPAM Service Objects  
**Custom Field 2: automation_key**
- Content Type: `IPAM > Service`
- Type: Text
- Name: `automation_key`
- Label: `Automation Key`
- Description: `Stable identifier for automation reconciliation`
- Required: No
- Weight: 100

#### For Security Address Objects (if not already present)
**Custom Field 3: ipam_backref** (should already exist)
- Content Type: `NetBox Security > Address`
- Type: Text
- Name: `ipam_backref`
- Label: `IPAM Backref`
- Description: `Reference to source IPAM object`
- Required: No

**Custom Field 4: automation_key**
- Content Type: `NetBox Security > Address`
- Type: Text
- Name: `automation_key`
- Label: `Automation Key`
- Description: `Stable identifier for automation reconciliation`
- Required: No
- Weight: 100

#### For Security Address Set Objects
**Custom Field 5: ipam_backref** (should already exist)
- Content Type: `NetBox Security > Address Set`
- Type: Text
- Name: `ipam_backref`
- Label: `IPAM Backref`
- Description: `Reference to source tag`
- Required: No

**Custom Field 6: automation_key**
- Content Type: `NetBox Security > Address Set`
- Type: Text
- Name: `automation_key`
- Label: `Automation Key`
- Description: `Stable identifier for automation reconciliation`
- Required: No
- Weight: 100

## Migration Steps

### Step 1: Tag Your IP Addresses

For each key IP address in IPAM that should sync to Security, add the base tags.

**Example IPs from your network (based on your config):**

| IP Address | Purpose | Existing Tags | Add Base Tags | automation_key |
|------------|---------|---------------|---------------|----------------|
| 192.168.20.3 | Caddy Proxy | (add if missing) | `managed-by-script`, `scope-hexs` | `ip:caddy` |
| 192.168.10.10 | Minecraft | (add if missing) | `managed-by-script`, `scope-hexs` | `ip:minecraft` |
| 192.168.10.32 | Mumble | (add if missing) | `managed-by-script`, `scope-hexs` | `ip:mumble` |
| 192.168.10.31 | BIND | (add if missing) | `managed-by-script`, `scope-hexs` | `ip:bind` |
| 192.168.20.2 | Pi-hole | (add if missing) | `managed-by-script`, `scope-hexs` | `ip:pihole` |

**How to apply:**

1. Navigate to **IPAM → IP Addresses**
2. Find each IP address
3. Click **Edit**
4. In **Tags** field, add: `managed-by-script`, `scope-hexs`
5. In **Custom Fields** section, set `automation_key` to the value from table above
6. Click **Save**

**Automation Key Naming Convention:**
- Use `ip:<purpose>` for IP addresses (e.g., `ip:caddy`, `ip:minecraft`)
- Keep it lowercase, use hyphens for multi-word (e.g., `ip:uptime-kuma`)
- Make it unique and descriptive

### Step 2: Tag and Configure Your Services

For each Service that should drive an Address Set:

**Example: Minecraft Service**

1. Navigate to **IPAM → Services**
2. Find "Minecraft" service (or create if missing)
3. Click **Edit**
4. **Bind to Device/VM**: Select the device running Minecraft
5. **IP Addresses**: Bind to `192.168.10.10` (or appropriate IP)
6. **Tags**: Add `managed-by-script`, `scope-hexs`, `svcminecraft`
7. **Custom Fields**: Set `automation_key` = `svc:minecraft:java`
8. Click **Save**

**Apply this pattern to all services:**

| Service Name | Protocol/Port | Bind to IP | Tags | automation_key |
|--------------|---------------|------------|------|----------------|
| Caddy HTTP | TCP/80 | 192.168.20.3 | `managed-by-script`, `scope-hexs`, `pathvia-caddy` | `svc:caddy:http` |
| Caddy HTTPS | TCP/443 | 192.168.20.3 | `managed-by-script`, `scope-hexs`, `pathvia-caddy` | `svc:caddy:https` |
| BIND DNS | UDP/53 | 192.168.10.31 | `managed-by-script`, `scope-hexs`, `svcbind` | `svc:bind:dns` |
| Pi-hole DNS | UDP/53 | 192.168.20.2 | `managed-by-script`, `scope-hexs`, `svcpihole` | `svc:pihole:dns` |
| Minecraft Java | TCP/25565 | 192.168.10.10 | `managed-by-script`, `scope-hexs`, `svcminecraft` | `svc:minecraft:java` |
| Mumble | TCP/64738 | 192.168.10.32 | `managed-by-script`, `scope-hexs`, `svcmumble` | `svc:mumble:voip` |

**Service automation_key convention:**
- Use `svc:<purpose>:<protocol>` (e.g., `svc:minecraft:java`, `svc:caddy:http`)
- For single-protocol services: `svc:<purpose>` (e.g., `svc:bind`)

### Step 3: Tag Devices (for monitoring)

If you have devices tagged with `monping` for monitoring:

1. Navigate to **Devices → Devices**
2. Find device (e.g., router, switches)
3. Click **Edit**
4. Ensure **Primary IPv4** is set
5. **Tags**: Add `managed-by-script`, `scope-hexs`, `monping`
6. **Custom Fields**: Set `automation_key` = `dev:<hostname>` (e.g., `dev:hex-s`)
7. Click **Save**

### Step 4: Verify Before Running Script

**Pre-flight checklist:**

1. ✅ All tags created in NetBox
2. ✅ All custom fields created for IP Address, Service, Security Address, Security Address Set
3. ✅ At least one IP address has both base tags + automation_key
4. ✅ At least one Service is bound to an IP, has base tags + intent tag + automation_key
5. ✅ Config file updated with `managed_tags_all` and `address_sets` entries

## Running the Migration

### Step 1: Dry Run (No Changes)

```bash
# Using the new script with new config
export NETBOX_API_KEY="your-api-token-here"

python3 ipam-to-security-v2.py \
  --config config-v2.toml \
  --debug \
  --show-payload
```

**Expected output:**
- Should list which IPs would be synced
- Should show which Address Sets would be created/updated
- Look for `[debug]` lines showing tag filtering
- No actual changes made (`--apply` not set)

**What to verify:**
- ✅ Only objects with base tags are selected
- ✅ Intent tags correctly select objects for address sets
- ✅ No unexpected objects are included
- ❌ If too many/few objects selected, review tags

### Step 2: Test with --apply (Make Changes)

```bash
python3 ipam-to-security-v2.py \
  --config config-v2.toml \
  --apply \
  --debug
```

**Expected output:**
```
CREATE  caddy.example.com  192.168.20.3/32  /api/ipam/ip-addresses/123/
CREATE  minecraft.example.com  192.168.10.10/32  /api/ipam/ip-addresses/124/
...
ADDRSET CREATE  caddy-access-services  pathvia-caddy  2
ADDRSET CREATE  minecraft-server  svcminecraft  1
...
Address Summary: created=5 updated=0 skipped=0
AddressSet Summary: created=7 updated=0 skipped=0
```

### Step 3: Verify in NetBox UI

1. Navigate to **Security → Addresses**
   - Should see new addresses created
   - Check one address:
     - Custom field `ipam_backref` should point to `/api/ipam/ip-addresses/NNN/`
     - Custom field `automation_key` should match source (e.g., `ip:caddy`)

2. Navigate to **Security → Address Sets**
   - Should see sets like `caddy-access-services`, `minecraft-server`
   - Check one set:
     - Should contain expected IP addresses
     - Custom field `ipam_backref` should be `/api/extras/tags/?slug=pathvia-caddy`
     - Custom field `automation_key` should match config (e.g., `set:caddy-access`)

### Step 4: Test Updates

**Test updating an existing Security Address:**

```bash
python3 ipam-to-security-v2.py \
  --config config-v2.toml \
  --apply \
  --update \
  --debug
```

**Expected output:**
```
UPDATE  caddy.example.com  192.168.20.3/32  /api/ipam/ip-addresses/123/
...
Address Summary: created=0 updated=5 skipped=0
```

**What to test:**
1. Change `dns_name` on an IP address in IPAM
2. Run script with `--apply --update`
3. Verify Security Address updated to match

## Troubleshooting

### No objects selected

**Problem:** Script runs but shows `created=0 updated=0 skipped=0`

**Cause:** No objects have all required `managed_tags_all`

**Solution:**
1. Check your config: `managed_tags_all = ["managed-by-script", "scope-hexs"]`
2. Verify IP addresses and Services have BOTH tags
3. Run with `--debug` to see which objects are fetched

### Address Set is empty

**Problem:** Address Set created but contains 0 addresses

**Cause:** Services with intent tag exist, but their bound IP addresses don't have base tags

**Solution:**
1. Find Service tagged with intent tag (e.g., `svcminecraft`)
2. Check which IP address(es) the Service is bound to
3. Add `managed-by-script` and `scope-hexs` tags to those IP addresses
4. Run script again

### IP address not in /32 format

**Problem:** Existing Security Addresses show `/24` but new ones show `/32`

**Cause:** Old script normalized only /24 → /32, new script normalizes all

**Solution:**
- Run with `--apply --update` to normalize existing addresses
- All addresses will become /32 (IPv4) or /128 (IPv6) for consistency

### Duplicate addresses created

**Problem:** Script creates new address instead of updating existing

**Cause:** `backref` or `automation_key` mismatch

**Solution:**
1. Check existing Security Address custom fields
2. Verify `ipam_backref` matches source object URL
3. Add matching `automation_key` to both source and Security object
4. Delete duplicate manually and run script with `--update`

## Rollback Plan

If you need to revert to the old script:

1. The old script (`ipam-to-security.py`) still works with old config (`config.toml`)
2. Security Addresses created by v2 have same structure (compatible)
3. New custom fields (`automation_key`) are simply ignored by old script
4. Base tags (`managed-by-script`, `scope-hexs`) won't break old script (just additional filters)

**To rollback:**
```bash
# Use old script with old config
python3 ipam-to-security.py --config config.toml --apply --update
```

## Next Steps After Migration

### 1. Enable automation_key matching everywhere

Once verified, add `automation_key` to all important objects for resilience.

### 2. Add scope tags for future expansion

If you add a second router or site:
- Create new scope tag: `scope-other-site`
- Duplicate config section with new `managed_tags_all`
- Run script separately for each scope

### 3. Consider adding source tags

For future multi-source scenarios (RouterOS + Cloudflare + AWS):
```toml
managed_tags_all = ["managed-by-script", "scope-hexs", "source-routeros"]
```

Then create separate configs for other sources:
```toml
managed_tags_all = ["managed-by-script", "scope-aws", "source-terraform"]
```

### 4. Set up automation

Once stable, add to cron:
```bash
# Run every 15 minutes
*/15 * * * * cd /opt/scripts && python3 ipam-to-security-v2.py --config config-v2.toml --apply --update 2>&1 | logger -t ipam-sync
```

## Quick Reference: Tag Strategy

### Base Tags (AND - all required)
- `managed-by-script` - Safety fence
- `scope-hexs` - Environment/location scope
- `source-routeros` - (Optional) Data source

### Intent Tags (OR - any match)
- `pathvia-caddy` - Services behind Caddy
- `svcbind`, `svcpihole`, `svcminecraft`, etc. - Service categories
- `monping`, `monhttp` - Monitoring targets

### automation_key Format
- IP Addresses: `ip:<purpose>` (e.g., `ip:caddy`)
- Services: `svc:<purpose>:<protocol>` (e.g., `svc:minecraft:java`)
- Devices: `dev:<hostname>` (e.g., `dev:hex-s`)
- Address Sets: `set:<purpose>` (e.g., `set:caddy-access`)

## Support

If you encounter issues:

1. Run with `--debug --show-payload` to see detailed output
2. Check NetBox API logs: **Background Tasks → View All**
3. Verify custom fields exist and are spelled correctly
4. Confirm tags are applied to objects (not just created)
5. Check that Services are actually bound to IP addresses
