# PR: Simplify Deploy Flow

## Summary

This PR simplifies deployment flow selection so `deploy.py` only checks two fields from the Nodes sheet:

1. If `Script URL` is set, run the Proxmox Helper Script.
2. If `Managed` is true, run `bootstrap.yaml`, `hardening.yaml`, and then any additional playbooks listed in `Playbooks`.

## Motivation

The previous implementation used a complex branching structure based on `Deployment Type` with multiple scenarios:
- `helper-script` + not managed
- `helper-script` + managed  
- `ansible` + managed
- Unhandled scenarios logged as warnings

This created confusion and required maintaining a `Deployment Type` column that was essentially redundant with `Script URL` and `Managed`.

## Changes

### New Function: `_parse_playbooks_value()`

Parses a comma-separated `Playbooks` cell into a list of playbook names.

```python
def _parse_playbooks_value(value: object) -> list[str]:
    """
    Parse a comma-separated Playbooks cell into a list of playbook names.
    
    Examples:
        "app.yaml, monitoring.yaml" -> ["app.yaml", "monitoring.yaml"]
        "" -> []
        None -> []
    """
```

### Modified: `run_ansible_playbooks()`

**Before:**
```python
def run_ansible_playbooks(hostname: str, config_path: Path) -> bool:
    playbooks = ["bootstrap.yaml", "hardening.yaml"]
    # ... run both playbooks
```

**After:**
```python
def run_ansible_playbooks(hostname: str, config_path: Path, 
                         extra_playbooks: list[str] | None = None) -> bool:
    playbooks = ["bootstrap.yaml", "hardening.yaml"]
    
    # Append extra playbooks if provided
    if extra_playbooks:
        playbooks.extend(extra_playbooks)
    # ... run all playbooks
```

### Rewritten: `main()` Logic

**Before** (complex branching):
```python
deployment_type = as_str(row.get("deployment_type")).lower()
managed = as_str(row.get("managed")).lower() in {"true", "yes", "1"}

# Scenario 1: helper-script only
if deployment_type == "helper-script" and not managed:
    # ...

# Scenario 2: helper-script + ansible
if deployment_type == "helper-script" and managed:
    # ...

# Scenario 3: ansible only
if deployment_type == "ansible" and managed:
    # ...

# Unhandled
logger.warning(f"Unhandled deployment scenario...")
```

**After** (simple independent checks):
```python
script_url = as_str(node_cfg.get("script_url", "")).strip()
managed = as_str(row.get("managed", "")).lower() in {"true", "yes", "1"}
playbooks_value = row.get("playbooks", "")

run_helper = bool(script_url)
run_ansible = managed

# Phase 1: Run helper if Script URL is set
if run_helper:
    success = run_proxmox_helper_script(...)
    if not success:
        return 1

# Phase 2: Run ansible if Managed is true
if run_ansible:
    extra_playbooks = _parse_playbooks_value(playbooks_value)
    ansible_success = run_ansible_playbooks(hostname, config_path, extra_playbooks)
    if not ansible_success:
        return 1
```

## Resulting Behavior

| Script URL | Managed | Playbooks | Result |
|-----------|---------|-----------|---------|
| Set | false | (ignored) | Helper script only |
| Empty | true | Empty | bootstrap + hardening |
| Empty | true | "app.yaml" | bootstrap + hardening + app.yaml |
| Set | true | Empty | Helper → bootstrap + hardening |
| Set | true | "app.yaml, monitoring.yaml" | Helper → bootstrap + hardening + app + monitoring |
| Empty | false | (ignored) | No-op (skip deployment) |

## Breaking Changes

**Removed dependency on `Deployment Type` column**:
- Old configs that relied on `Deployment Type` being set will need migration
- Migration: Set `Script URL` and/or `Managed` instead

**Migration guide**:
- `Deployment Type: helper-script` + `Managed: false` → Set `Script URL`, leave `Managed` empty/false
- `Deployment Type: helper-script` + `Managed: true` → Set both `Script URL` and `Managed: true`
- `Deployment Type: ansible` + `Managed: true` → Leave `Script URL` empty, set `Managed: true`

## Notes

- **Playbooks column format**: Comma-separated list of playbook names
- **Playbook resolution**: Extra playbooks are resolved relative to `ansible/playbooks/` (same as built-in playbooks)
- **Playbooks are ignored** unless `Managed` is true
- **No-op behavior**: Nodes with neither `Script URL` nor `Managed=true` are skipped with an info message

## Testing

- [x] Syntax validation: `python3 -m py_compile homelab/deploy.py`
- [ ] Manual: Deploy with `Script URL` only
- [ ] Manual: Deploy with `Managed=true` only
- [ ] Manual: Deploy with both `Script URL` and `Managed=true`
- [ ] Manual: Deploy with extra playbooks in `Playbooks` column
- [ ] Manual: Verify no-op behavior when neither field is set

## Files Changed

- `homelab/deploy.py`: +55 lines, -105 lines
  - Added `_parse_playbooks_value()` function
  - Modified `run_ansible_playbooks()` to accept `extra_playbooks`
  - Simplified `main()` deployment logic
- `docs/pr-simplify-deploy-flow.md`: New documentation

---

**Impact**: Simplifies deployment logic, removes `Deployment Type` dependency, adds support for custom playbooks

## Additional Fixes (Latest Commit)

### 1. Script URL + Proxmox Node Validation

Added validation to prevent deployment failures:

```python
if run_helper:
    proxmox_node = as_str(row.get("proxmox_node", "")).strip()
    if not proxmox_node:
        logger.error("Script URL is set but Proxmox Node is blank...")
        return 1
```

**Behavior**: If `Script URL` is set but `Proxmox Node` is blank, deployment errors immediately with a clear message.

### 2. Interactive Node Selection Menu

Made the `hostname` argument optional. When omitted, displays an interactive menu:

```bash
$ python -m deploy

============================================================
  Select Node to Deploy
============================================================

  1. pve-node1         [Helper]
  2. docker-host       [Ansible]
  3. k8s-master        [Helper + Ansible]
  4. pihole            [Ansible]

============================================================
Enter number (or 'q' to quit): _
```

**Implementation**:
- Added `_select_deployable_node()` function
- Filters nodes where `Managed=true` OR `Script URL` is set
- Displays deployment type label for each node
- Supports keyboard shortcuts: number to select, 'q' to quit, Ctrl+C to cancel

**Usage**:
```bash
# Interactive menu
python -m deploy

# Direct (original behavior)
python -m deploy myhost
```

### Updated Testing Checklist

- [x] Syntax validation
- [x] Hostname argument is optional
- [x] Menu function exists and is called
- [x] Proxmox Node validation added
- [ ] Manual: Test interactive menu with multiple nodes
- [ ] Manual: Test menu with only one deployable node
- [ ] Manual: Test menu with no deployable nodes
- [ ] Manual: Test validation: Script URL but no Proxmox Node
- [ ] Manual: Original behavior (hostname provided) still works
