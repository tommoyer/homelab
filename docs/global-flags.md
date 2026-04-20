# Global Flags: --debug and --apply

## Overview

The homelab CLI now supports global `--debug` and `--apply` flags that work across all commands, eliminating the need to specify them per-command.

## Usage

### Global Flags (New Way - Recommended)

```bash
# Apply changes across all commands that support it
python -m homelab --apply deploy hostname
python -m homelab --apply dns
python -m homelab --apply caddy

# Enable debug logging across all commands
python -m homelab --debug deploy hostname
python -m homelab --debug mikrotik

# Combine both flags
python -m homelab --debug --apply deploy hostname
python -m homelab --apply --debug dns

# Run mode with global flags
python -m homelab --apply run --pihole --caddy
python -m homelab --debug run --all
```

## Implementation Details

### Flag Forwarding

The CLI automatically forwards global flags to subcommands:

1. **Parse global flags** before the command name
2. **Forward to subcommand** if the command supports it
3. **Reject per-command usage** of `--debug` / `--apply`

### Rules

- `--debug` and `--apply` are **global-only** flags
- They must appear before the command name
- If passed after a command, the CLI returns an error

### Run Mode

The `run` mode uses only global `--apply`:

```bash
# Apply all features
python -m homelab --apply run

# Apply specific features with debug
python -m homelab --debug --apply run --dns
```

## Benefits

✅ **Consistency**: Same flags work everywhere  
✅ **Convenience**: No need to remember which commands support which flags  
✅ **Clarity**: Flags before command makes intent clear  
✅ **Strictness**: One clear way to pass shared execution flags

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
python -m homelab --apply dns
python -m homelab --apply caddy

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
