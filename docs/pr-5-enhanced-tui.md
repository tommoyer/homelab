# PR #5: Enhanced TUI with Per-Command Flag Configuration

## Overview

This PR transforms the homelab TUI from a simple launcher into an interactive configuration interface. Users can now toggle flags (like `--apply`, `--debug`, `--sudo`) before running each command, making the TUI a practical alternative to remembering CLI syntax.

## Before (Simple TUI)

The original TUI (`homelab/ui.py`, 99 lines):
- Listed available commands
- Selected command → ran immediately with no arguments
- No way to control `--apply`, `--debug`, or tool-specific flags
- **Limitation**: Users had to exit the TUI and use CLI for any flag customization

## After (Enhanced TUI)

The new TUI (`homelab/ui.py`, 323 lines):

### Main Menu
```
═══════════════════════════════════════════════════════════
  HOMELAB TOOLS MENU
═══════════════════════════════════════════════════════════
Use ↑/↓ to select, Enter to configure/run, q to quit
───────────────────────────────────────────────────────────

▶ caddy             Generate Caddyfile from Google Sheets
  deploy            Deploy homelab node via Ansible
  dnscontrol        Generate DNSControl config from Sheets
  mikrotik          Generate MikroTik service config
  pihole            Generate Pi-hole v6 TOML config
  subnet_assign     Interactive subnet/IP assignment
```

### Configuration Menu (Example: pihole)
```
═══════════════════════════════════════════════════════════
  Configure: pihole
═══════════════════════════════════════════════════════════
Use ↑/↓ to select, Space to toggle, Enter to confirm
───────────────────────────────────────────────────────────

▶ [×] --apply          Apply changes to remote host
  [ ] --debug          Enable debug logging
  [ ] --sudo           Use sudo when applying
      --tailnet        <empty>
───────────────────────────────────────────────────────────
  [Run Command]
  [Cancel]
```

**Interaction Flow**:
1. Select command from main menu (Enter)
2. Configure flags in detail screen:
   - Use **Space** to toggle boolean flags (`--apply`, `--debug`, `--sudo`)
   - Navigate with **↑/↓**
   - Select **[Run Command]** when ready, or **[Cancel]** to go back
3. Command runs with selected flags: `python -m pihole --apply --debug`
4. See output and exit code
5. **Press Enter** to return to main menu

## Architecture

### New Components

#### `FlagConfig` dataclass
```python
@dataclass
class FlagConfig:
    name: str                    # "--apply"
    description: str             # "Apply changes to remote host"
    flag_type: str              # "bool", "string", "choice"
    default: Any = None
    enabled: bool = False        # Toggle state for bools
    value: str | None = None    # Value for strings
```

#### `CommandConfig` dataclass
```python
@dataclass
class CommandConfig:
    entry: MenuEntry
    flags: list[FlagConfig]
```

#### `_discover_flags(command_name, module)`
- Maps each command to its high-value flags
- Returns a list of `FlagConfig` objects for the configuration menu
- **Extensible**: Add new flags to `known_flags` and `command_flag_map`

#### `_config_menu(stdscr, config)`
- Renders the configuration screen
- Handles Space (toggle), Enter (confirm), q/ESC (cancel)
- Returns `True` if user selected "Run", `False` if cancelled

#### `_build_argv_from_config(config)`
- Converts `CommandConfig` into CLI arguments
- Example: `[--apply, --debug]` for enabled flags

### Enhanced Main Loop

```python
while True:
    # 1. Main menu: select command
    selected_entry = curses.wrapper(lambda stdscr: _main_menu(...))
    if selected_entry is None:
        return 0  # User quit
    
    # 2. Discover flags for selected command
    flags = _discover_flags(selected_entry.name, module)
    config = CommandConfig(entry=selected_entry, flags=flags)
    
    # 3. Configuration menu
    should_run = curses.wrapper(lambda stdscr: _config_menu(stdscr, config))
    if not should_run:
        continue  # Back to main menu
    
    # 4. Build argv and run
    command_argv = _build_argv_from_config(config)
    exit_code = selected_entry.runner(command_argv)
    
    # 5. Show result and wait
    input("Press Enter to return to menu...")
```

## Supported Flags by Command

| Command | Flags |
|---------|-------|
| `pihole` | `--apply`, `--debug`, `--sudo`, `--tailnet` |
| `dnscontrol` | `--apply`, `--debug` |
| `caddy` | `--apply`, `--debug` |
| `deploy` | `--debug` |
| `mikrotik` | `--debug` |
| `subnet_assign` | *(no configurable flags)* |

**Adding new flags**: Update `known_flags` and `command_flag_map` in `_discover_flags()`.

## Benefits

1. **Discoverability**: Users see available flags without reading `--help`
2. **Safety**: Toggle `--apply` visually instead of typing it wrong
3. **Convenience**: No need to remember flag syntax
4. **Workflow**: Configure → Run → Review → Repeat from same interface
5. **Accessibility**: Visual toggles are clearer than remembering which flags exist

## Future Enhancements

### String/Choice Inputs (Not Yet Implemented)
```python
# Future: Edit --tailnet value inline
  --tailnet        [Edit: "duckbill-frog.ts.net"]
```

Press **e** or **Enter** on string fields to open an input prompt.

### Flag Discovery via Introspection
Instead of hardcoded `command_flag_map`, introspect each module's `build_parser()` to discover flags automatically:

```python
def _discover_flags_dynamic(module):
    parser = module.build_parser([])
    for action in parser._actions:
        if action.dest not in ["help", "config"]:
            yield FlagConfig(...)
```

This would make the TUI automatically pick up new flags as they're added to tools.

### Save Configurations
Allow users to save flag presets:
```
[Save Current Config]
[Load Preset: "apply-with-sudo"]
```

### Command History
Track recently run commands with their flags for quick re-execution.

## Testing

- [x] Syntax validation: `python3 -m py_compile homelab/ui.py`
- [ ] Manual testing: `python -m homelab_ui` (requires TTY)
  - [x] Main menu navigation (↑/↓/Enter/q)
  - [ ] Config menu navigation and flag toggling
  - [ ] Running commands with selected flags
  - [ ] Return to menu after command completes

## Backward Compatibility

- **CLI unchanged**: `python -m homelab pihole --apply` still works
- **Old TUI behavior preserved**: If a command has no flags, it runs immediately (no config screen)
- **Wrapper unchanged**: `homelab_ui.py` still delegates to `homelab.ui.main()`

## Files Changed

- `homelab/ui.py`: Enhanced from 99 → 323 lines (3.2× larger)
  - Added `FlagConfig`, `CommandConfig` dataclasses
  - Added `_discover_flags()`, `_config_menu()`, `_build_argv_from_config()`
  - Enhanced `_main_menu()` with better formatting
  - Enhanced `main()` loop with config → run → repeat flow

- `docs/pr-5-enhanced-tui.md`: This documentation

---

**Part of homelab refactoring series**: PR #5 of 4 (bonus!), providing an interactive TUI alternative to CLI flag syntax.
