# Script Update Summary: v1 → v2

## What Changed

### 1. Tag Filtering Logic

**v1 (Old):**
```python
# Single tag filter applied to everything
ipam_params = {"tag": "secsync", "limit": "200"}
```

**v2 (New):**
```python
# Multiple base tags (AND logic) + intent tags (OR logic)
managed_tags_all = ["managed-by-script", "scope-hexs"]
intent_tags_any = ["pathvia-caddy", "svcminecraft", ...]

# Fetches objects that have ALL base tags AND ANY intent tag
```

**Why:** Prevents accidentally syncing unrelated objects. Creates a clear "safety fence" for automation.

---

### 2. Address Normalization

**v1 (Old):**
```python
# Only converted /24 to /32
if interface.version == 4 and interface.network.prefixlen == 24:
    return f"{interface.ip}/32"
```

**v2 (New):**
```python
# Converts ALL non-host addresses to host addresses
if interface.version == 4:
    if interface.network.prefixlen != 32:
        return f"{interface.ip}/32"
elif interface.version == 6:
    if interface.network.prefixlen != 128:
        return f"{interface.ip}/128"
```

**Why:** Ensures ALL Security Addresses represent individual hosts, not networks. More consistent and correct for firewall rules.

---

### 3. Object Matching

**v1 (Old):**
```python
# Only matched by ipam_backref
existing = existing_by_backref.get(backref_value)
```

**v2 (New):**
```python
# Matches by ipam_backref first, falls back to automation_key
existing = existing_by_backref.get(backref_value)
if not existing and automation_key:
    existing = existing_by_automation_key.get(automation_key)
```

**Why:** Allows renaming/moving objects in IPAM without losing sync. More resilient to changes.

---

### 4. Configuration Structure

**v1 (Old):**
```toml
[ipam_to_security]
tag = "secsync"  # Single global tag
service_address_sets = [
  { tag = "pathvia-caddy", address_set = "caddy-access-services" },
]
```

**v2 (New):**
```toml
[ipam_to_security]
managed_tags_all = ["managed-by-script", "scope-hexs"]  # Base tags

[[ipam_to_security.address_sets]]
intent_tags_any = ["pathvia-caddy"]
address_set = "caddy-access-services"
automation_key = "set:caddy-access"
description = "Services accessible via Caddy"
```

**Why:** Clearer separation of concerns. Base tags = what to touch, intent tags = what to do with it.

---

### 5. Address Set Tagging

**v1 (Old):**
```python
# Each address set requires exactly one tag
for mapping in service_address_sets:
    tag = mapping["tag"]  # Single tag
    params = {"tag": tag, ...}
```

**v2 (New):**
```python
# Each address set can match multiple tags (OR logic)
for mapping in service_address_sets:
    intent_tags = mapping["intent_tags"]  # List of tags
    records = fetch_records_with_any_tags(..., intent_tags, ...)
```

**Why:** Flexibility. Can group multiple related tags into one address set. Easier to reorganize without changing infrastructure.

---

## Configuration Migration

### Old config.toml
```toml
[ipam_to_security]
tag = "secsync"
backref_field = "ipam_backref"
service_address_sets = [
  { tag = "pathvia-caddy", address_set = "caddy-access-services", sources = ["services"] },
]
```

### New config-v2.toml
```toml
[ipam_to_security]
managed_tags_all = ["managed-by-script", "scope-hexs"]
backref_field = "ipam_backref"
automation_key_field = "automation_key"

[[ipam_to_security.address_sets]]
intent_tags_any = ["pathvia-caddy"]
address_set = "caddy-access-services"
sources = ["services"]
automation_key = "set:caddy-access"
description = "Services accessible via Caddy"
```

---

## NetBox Data Changes Required

### IP Addresses (IPAM)

**Before (v1):**
- Tag: `secsync`

**After (v2):**
- Tags: `managed-by-script`, `scope-hexs`
- Custom Field: `automation_key = "ip:caddy"` (optional but recommended)

### Services (IPAM)

**Before (v1):**
- Tag: `pathvia-caddy` (or other intent tag)
- Bound to IP address

**After (v2):**
- Tags: `managed-by-script`, `scope-hexs`, `pathvia-caddy`
- Bound to IP address
- Custom Field: `automation_key = "svc:caddy:http"` (optional but recommended)

### Security Addresses

**Before (v1):**
- Custom Field: `ipam_backref`

**After (v2):**
- Custom Field: `ipam_backref` (same)
- Custom Field: `automation_key` (new, optional)

### Security Address Sets

**Before (v1):**
- Custom Field: `ipam_backref` (pointed to tag)

**After (v2):**
- Custom Field: `ipam_backref` (same)
- Custom Field: `automation_key` (new, optional)

---

## Running the Scripts

### v1 (Old)
```bash
export NETBOX_API_KEY="..."
python3 ipam-to-security.py --config config.toml --apply --update
```

### v2 (New)
```bash
export NETBOX_API_KEY="..."
python3 ipam-to-security-v2.py --config config-v2.toml --apply --update
```

---

## Key Benefits of v2

1. **Safety**: `managed_tags_all` prevents accidental syncing of wrong objects
2. **Scope**: Easy to separate different environments/sites with scope tags
3. **Resilience**: `automation_key` allows renaming without breaking sync
4. **Flexibility**: `intent_tags_any` allows OR logic (multiple tags → one set)
5. **Correctness**: Proper /32 and /128 normalization for all IPs
6. **Future-proof**: Easy to add new scopes, sources, or reorganize tags

---

## Backward Compatibility

**Good news:** v1 and v2 can coexist during migration.

- Security objects created by v1 work with v2
- v2 respects existing `ipam_backref` fields
- New fields (`automation_key`) are optional
- Old tags still work (just need to add base tags alongside)

**Migration strategy:**
1. Run v1 to establish baseline
2. Add base tags + custom fields to NetBox
3. Run v2 in dry-run mode (`--debug`, no `--apply`)
4. Verify output looks correct
5. Run v2 with `--apply --update`
6. Verify in NetBox UI
7. Switch cron jobs to v2

---

## Example: Before and After

### Scenario: Sync Caddy service to Security

**v1 Setup:**
```
IPAM IP Address: 192.168.20.3
  - Tag: secsync

IPAM Service: Caddy HTTPS (TCP/443)
  - Tag: pathvia-caddy
  - Bound to: 192.168.20.3

Config:
  tag = "secsync"
  service_address_sets = [
    { tag = "pathvia-caddy", address_set = "caddy-access-services" }
  ]

Result:
  Security Address: 192.168.20.3/32
    - ipam_backref: /api/ipam/ip-addresses/123/
  
  Security Address Set: caddy-access-services
    - Contains: [192.168.20.3/32]
    - ipam_backref: /api/extras/tags/?slug=pathvia-caddy
```

**v2 Setup:**
```
IPAM IP Address: 192.168.20.3
  - Tags: managed-by-script, scope-hexs
  - automation_key: ip:caddy

IPAM Service: Caddy HTTPS (TCP/443)
  - Tags: managed-by-script, scope-hexs, pathvia-caddy
  - Bound to: 192.168.20.3
  - automation_key: svc:caddy:https

Config:
  managed_tags_all = ["managed-by-script", "scope-hexs"]
  
  [[address_sets]]
  intent_tags_any = ["pathvia-caddy"]
  address_set = "caddy-access-services"
  automation_key = "set:caddy-access"

Result:
  Security Address: 192.168.20.3/32
    - ipam_backref: /api/ipam/ip-addresses/123/
    - automation_key: ip:caddy
  
  Security Address Set: caddy-access-services
    - Contains: [192.168.20.3/32]
    - ipam_backref: /api/extras/tags/?slug=pathvia-caddy
    - automation_key: set:caddy-access
```

**Key difference:** More metadata for resilience, clearer intent separation, better safety fence.

---

## Checklist: Am I Ready to Migrate?

- [ ] I understand why `managed_tags_all` is important (safety fence)
- [ ] I created tags: `managed-by-script`, `scope-hexs` in NetBox
- [ ] I created `automation_key` custom field for IP Address
- [ ] I created `automation_key` custom field for Service  
- [ ] I created `automation_key` custom field for Security Address
- [ ] I created `automation_key` custom field for Security Address Set
- [ ] I tagged at least one IP with base tags for testing
- [ ] I tagged at least one Service with base + intent tags
- [ ] I updated config-v2.toml with my address_sets
- [ ] I ran v2 script in dry-run mode (`--debug`, no `--apply`)
- [ ] I verified the dry-run output looks correct
- [ ] I'm ready to run with `--apply` and verify in NetBox UI

Once all checked, you're ready to migrate!
