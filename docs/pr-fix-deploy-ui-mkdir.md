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
