# PR: Fix deploy.py mkdir Error and Curses UI

## Summary

This PR fixes two issues with `deploy.py`:

1. **mkdir error**: Fixed `'str' object has no attribute 'mkdir'` error when `render_dir` is retrieved from config
2. **Inconsistent UI**: Replaced plain text menu with curses-based UI for consistency with `homelab_ui`

---

## Issue 1: mkdir Error

### Problem

When running deploy with a `render_dir` configured in TOML, the script would crash with:

```
Failed to write rendered vars file: 'str' object has no attribute 'mkdir'
```

### Root Cause

On line 763, `render_dir` was retrieved from `effective_settings.get("render_dir")`, which returns a string when the value comes from the config file. Later, on line 680, the code called `out_dir.mkdir()`, expecting a `Path` object.

**Before:**
```python
render_dir: Path | None = effective_settings.get("render_dir")
# ... later ...
out_dir.mkdir(parents=True, exist_ok=True)  # ❌ Fails if render_dir is a string
```

### Solution

Convert the string to a `Path` object when retrieving from settings:

**After:**
```python
render_dir_raw = effective_settings.get("render_dir")
render_dir: Path | None = Path(render_dir_raw) if render_dir_raw else None
```

---

## Issue 2: Inconsistent UI

### Problem

The homelab tools use two different UI styles:

- **homelab_ui** (`homelab/ui.py`): Professional curses-based menu with arrow key navigation
- **deploy node selection**: Plain text menu requiring manual number entry

This created an inconsistent user experience.

**Old deploy menu (plain text):**
```
============================================================
  Select Node to Deploy
============================================================

  1. pve-node1         [Helper]
  2. docker-host       [Ansible]

============================================================
Enter number (or 'q' to quit): _
```

### Solution

Rewrote `_select_deployable_node()` to use curses, matching the `homelab_ui` style.

**New deploy menu (curses):**
```
============================================================
  SELECT NODE TO DEPLOY
============================================================
Use ↑/↓ to select, Enter to deploy, q to quit
------------------------------------------------------------

▶ pve-node1           [Helper]
  docker-host         [Ansible]
  k8s-master          [Helper + Ansible]
```

### Implementation

**Added:**
- `import curses` to imports
- Internal `_curses_menu(stdscr)` function inside `_select_deployable_node()`
- Arrow key navigation (↑/↓)
- Visual selection indicator (▶)
- Keyboard shortcuts: Enter (select), q/Q/ESC (quit)
- Graceful handling of terminal resize and keyboard interrupts

**Key differences from old implementation:**
| Feature | Old (text) | New (curses) |
|---------|-----------|--------------|
| Navigation | Type number | Arrow keys ↑/↓ |
| Selection | Press Enter after typing | Press Enter on highlighted item |
| Visual indicator | None | ▶ shows current selection |
| Quit | Type 'q' + Enter | Press 'q' instantly |
| Consistency | Different from homelab_ui | Matches homelab_ui exactly |

---

## Benefits

### Fix 1: mkdir Error
✅ **Reliability**: No more crashes when `render_dir` is configured  
✅ **Correctness**: Properly handles Path vs string types  
✅ **Backward compatible**: Works with both CLI `--render-dir` and config `render_dir`

### Fix 2: Curses UI
✅ **Consistency**: All menus now use the same curses-based UI  
✅ **User experience**: Arrow keys more intuitive than typing numbers  
✅ **Professional**: Matches modern TUI conventions  
✅ **Accessibility**: Immediate feedback with visual selection indicator

---

## Testing

### Fix 1: render_dir
- [x] Syntax validation
- [ ] Manual: Deploy with `render_dir` set in config.toml
- [ ] Manual: Deploy with `--render-dir` CLI argument
- [ ] Manual: Deploy without render_dir (uses default)

### Fix 2: Curses UI
- [x] Syntax validation
- [ ] Manual: Run `python -m deploy` without hostname
- [ ] Manual: Navigate with arrow keys
- [ ] Manual: Select node with Enter
- [ ] Manual: Quit with 'q'
- [ ] Manual: Cancel with Ctrl+C or ESC

---

## Files Changed

- `homelab/deploy.py`:
  - Added `import curses`
  - Fixed `render_dir` to properly convert string to Path
  - Rewrote `_select_deployable_node()` with curses-based UI
- `docs/pr-fix-deploy-ui-mkdir.md`: This documentation

---

## Code Changes Summary

### render_dir Fix
```python
# Before
render_dir: Path | None = effective_settings.get("render_dir")

# After  
render_dir_raw = effective_settings.get("render_dir")
render_dir: Path | None = Path(render_dir_raw) if render_dir_raw else None
```

### Curses Menu
```python
def _select_deployable_node(nodes_df: pd.DataFrame) -> str | None:
    # ... build deployable list ...
    
    def _curses_menu(stdscr) -> str | None:
        curses.curs_set(0)
        selected = 0
        
        while True:
            stdscr.clear()
            # Draw header
            # Draw menu items with ▶ for selected
            
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q"), 27):  # Quit
                return None
            elif ch == curses.KEY_UP:
                selected = (selected - 1) % len(deployable)
            elif ch == curses.KEY_DOWN:
                selected = (selected + 1) % len(deployable)
            elif ch in (10, 13, curses.KEY_ENTER):  # Select
                return deployable[selected]["hostname"]
    
    return curses.wrapper(_curses_menu)
```

---

**Impact**: Fixes critical mkdir error and provides consistent, professional UI across all tools

## Additional Enhancement: Global Flags (Latest Commit)

### Problem

Flags like `--debug` and `--apply` had to be specified per-command:

```bash
python -m homelab deploy hostname --apply --debug
python -m homelab pihole --apply
python -m homelab caddy --debug --apply
```

This was:
- Inconsistent (had to remember flag order for each command)
- Verbose (repetitive flag placement)
- Easy to forget (especially --apply in production scripts)

### Solution

Moved `--debug` and `--apply` to **global flags** that work before any command:

```bash
# New way (recommended)
python -m homelab --apply deploy hostname
python -m homelab --debug --apply pihole
python -m homelab --apply run --pihole --caddy

# Old way (still works)
python -m homelab deploy hostname --apply --debug
```

### Implementation

**Changes to `homelab/cli.py`:**

1. **Updated `_parse_global_options()`**
   - Now parses `--apply` in addition to `--debug`
   - Returns `(debug, apply, remaining_argv)` tuple

2. **Enhanced flag forwarding in `main()`**
   - Automatically forwards `--debug` to: deploy, pihole, caddy, dnscontrol, mikrotik
   - Automatically forwards `--apply` to: deploy, pihole, caddy, dnscontrol
   - Checks if flag already in argv to avoid duplicates

3. **Updated `_run_mode()`**
   - Now accepts `apply` parameter
   - Global `--apply` works with run mode

4. **Updated help text**
   - Shows both flags as global options

### Flag Support Matrix

| Command | --debug | --apply |
|---------|---------|---------|
| deploy | ✅ | ✅ |
| pihole | ✅ | ✅ |
| caddy | ✅ | ✅ |
| dnscontrol | ✅ | ✅ |
| mikrotik | ✅ | ❌ |
| subnet_assign | ❌ | ❌ |

### Benefits

✅ **Consistency**: Same flag placement across all commands  
✅ **Convenience**: One flag affects all relevant commands  
✅ **Clarity**: Intent is clear when flags come before command  
✅ **Backward compatible**: Per-command flags still work

### Examples

**Before:**
```bash
# Deploy with apply
python -m homelab deploy hostname --apply --debug

# Run multiple tools with apply
python -m homelab run --apply --pihole --caddy --dnscontrol
```

**After:**
```bash
# Deploy with apply (cleaner)
python -m homelab --debug --apply deploy hostname

# Run multiple tools with apply (same)
python -m homelab --apply run --pihole --caddy --dnscontrol
```

### Documentation

See `docs/global-flags.md` for comprehensive usage guide.

## Latest Enhancement: TUI Global Flags (Current Commit)

### Overview

The homelab TUI now displays global `--debug` and `--apply` flags at the top of the main menu, allowing users to toggle them once and have them apply to all subsequent commands.

### New TUI Layout

```
════════════════════════════════════════════════════════════
  HOMELAB TOOLS MENU
════════════════════════════════════════════════════════════
Use ↑/↓ to select, Space to toggle flags, Enter to run, q to quit
────────────────────────────────────────────────────────────
Global Flags:
▶ [×] --debug         Enable verbose debug logging
  [ ] --apply         Apply changes (deploy, pihole, caddy, dnscontrol)
────────────────────────────────────────────────────────────
Commands:
  caddy              Generate Caddyfile from Google Sheets
  deploy             Deploy homelab node via Ansible
  dnscontrol         Generate DNSControl config from Sheets
  mikrotik           Generate MikroTik service config
  pihole             Generate Pi-hole v6 TOML config
  subnet_assign      Interactive subnet/IP assignment
```

### How It Works

**Navigation:**
- **↑/↓ keys**: Navigate between global flags and commands
- **Space**: Toggle selected global flag (×=enabled, blank=disabled)
- **Enter**: Run selected command with global flags applied
- **q**: Quit

**Flag Persistence:**
- Global flags persist across menu iterations
- Set `--apply` once, run multiple commands
- Flags remain enabled when returning to menu after command execution

**Flag Forwarding:**
- Global flags automatically added to command argv
- Only added if command supports the flag
- Command-specific flags take precedence over global flags

### Supported Commands

| Command | Global --debug | Global --apply |
|---------|---------------|---------------|
| caddy | ✅ | ✅ |
| deploy | ✅ | ✅ |
| dnscontrol | ✅ | ✅ |
| mikrotik | ✅ | ❌ |
| pihole | ✅ | ✅ |
| subnet_assign | ❌ | ❌ |

### Example Workflow

**Scenario**: Update production configs

1. Launch TUI: `python -m homelab_ui`
2. Navigate to `--apply` flag (press ↓ once)
3. Press **Space** to enable: `[×] --apply`
4. Navigate to `pihole` command
5. Press **Enter** → runs `pihole --apply`
6. Returns to menu (apply still enabled)
7. Navigate to `caddy`
8. Press **Enter** → runs `caddy --apply`
9. Returns to menu (apply still enabled)
10. Navigate to `dnscontrol`
11. Press **Enter** → runs `dnscontrol --apply`

**Result**: All three commands applied changes without toggling flags each time.

### Benefits

✅ **One-time setup**: Enable flags once for entire session  
✅ **Consistent with CLI**: Matches `python -m homelab --apply` behavior  
✅ **Visual feedback**: See which global flags are active  
✅ **Efficient workflow**: No repetitive flag toggling  
✅ **Flexible**: Can still toggle per-command flags in config menu

### Implementation

**Added `GlobalFlags` dataclass:**
```python
@dataclass
class GlobalFlags:
    """Global flags that apply to all commands."""
    debug: bool = False
    apply: bool = False
```

**Enhanced main menu:**
- Shows global flags section above commands
- Handles Space key for toggling
- Updates selected index for all items (flags + commands)

**Command execution:**
- Checks if command supports each global flag
- Inserts global flags at beginning of argv
- Skips if flag already present in command-specific config

### Testing Checklist

- [x] Syntax validation
- [ ] Manual: Navigate to global flags with arrow keys
- [ ] Manual: Toggle --debug with Space
- [ ] Manual: Toggle --apply with Space
- [ ] Manual: Run command with --debug enabled globally
- [ ] Manual: Run command with --apply enabled globally
- [ ] Manual: Verify flags persist when returning to menu
- [ ] Manual: Verify command-specific flags override global flags
