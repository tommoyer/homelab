# Global Flags: --debug and --apply

## Overview

The homelab CLI now supports global `--debug` and `--apply` flags that work across all commands, eliminating the need to specify them per-command.

## Usage

### Global Flags (New Way - Recommended)

```bash
# Apply changes across all commands that support it
python -m homelab --apply deploy hostname
python -m homelab --apply pihole
python -m homelab --apply caddy
python -m homelab --apply dnscontrol

# Enable debug logging across all commands
python -m homelab --debug deploy hostname
python -m homelab --debug mikrotik

# Combine both flags
python -m homelab --debug --apply deploy hostname
python -m homelab --apply --debug pihole

# Run mode with global flags
python -m homelab --apply run --pihole --caddy
python -m homelab --debug run --all
```

### Per-Command Flags (Still Supported)

```bash
# Old way still works for backward compatibility
python -m homelab deploy hostname --apply --debug
python -m homelab pihole --apply
```

## Flag Support by Command

| Command | --debug | --apply |
|---------|---------|---------|
| `deploy` | ✅ | ✅ |
| `pihole` | ✅ | ✅ |
| `caddy` | ✅ | ✅ |
| `dnscontrol` | ✅ | ✅ |
| `mikrotik` | ✅ | ❌ |
| `subnet_assign` | ❌ | ❌ |

## Implementation Details

### Flag Forwarding

The CLI automatically forwards global flags to subcommands:

1. **Parse global flags** before the command name
2. **Forward to subcommand** if the command supports it
3. **Preserve per-command flags** if explicitly provided

### Priority Rules

- **Per-command flags take precedence** over global flags
- If `--apply` appears in both places, only one is forwarded
- Global flags are inserted at the beginning of command arguments

### Run Mode

The `run` mode now accepts global `--apply`:

```bash
# Apply all features
python -m homelab --apply run

# Apply specific features with debug
python -m homelab --debug --apply run --pihole --dnscontrol
```

## Benefits

✅ **Consistency**: Same flags work everywhere  
✅ **Convenience**: No need to remember which commands support which flags  
✅ **Clarity**: Flags before command makes intent clear  
✅ **Backward compatible**: Old per-command flags still work

## Examples

### Before (Per-Command Flags)

```bash
# Had to specify --apply for each command
python -m homelab pihole --apply
python -m homelab caddy --apply
python -m homelab dnscontrol --apply

# Had to remember which commands support --debug
python -m homelab deploy hostname --debug --apply
```

### After (Global Flags)

```bash
# One flag applies to all
python -m homelab --apply pihole
python -m homelab --apply caddy
python -m homelab --apply dnscontrol

# Clear and consistent
python -m homelab --debug --apply deploy hostname
```

## Migration Guide

### Update Your Scripts

**Old:**
```bash
./deploy.sh hostname --apply --debug
```

**New:**
```bash
python -m homelab --debug --apply deploy hostname
```

**Or keep using per-command flags** - both work!

---

**Introduced in**: PR #9 (fix/deploy-ui-and-mkdir branch)
