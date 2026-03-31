# PR #3: Module Decomposition into Packages

## Overview

This PR addresses code organization by splitting large monolithic modules (1000+ lines) into well-structured packages. This improves maintainability, testability, and makes it easier to navigate and understand the codebase.

## Problem

Several modules have grown beyond manageable size:

| Module | Lines | Issue |
|--------|-------|-------|
| `mikrotik_prompt.py` | 1,396 | Mixes data loading, UI logic, form handling, and command rendering |
| `deploy.py` | 809 | Combines node config extraction, Ansible orchestration, and helper scripts |
| `caddyfile.py` | 718 | Blends sheet parsing, conflict resolution, and template rendering |
| `pihole.py` | 661 | Mixes sheet parsing, DNS resolution logic, and TOML generation |

Large files make it hard to:
- Find specific functionality quickly
- Test individual components in isolation
- Understand dependencies and data flow
- Onboard new contributors

## Proposed Structure

### Example: `mikrotik_prompt` → `homelab/mikrotik/`

```
homelab/mikrotik/
├── __init__.py          # Public API: main() function
├── __main__.py          # Enable `python -m mikrotik` (delegates to __init__.main)
├── data.py              # Sheet loading: _load_sheet_df, _prefill_from_services_sheet, etc.
├── models.py            # Data classes: ServiceFormData, ParsedInput
├── ui.py                # Interactive prompts: _run_form_ui, _run_confirmation_ui
├── render.py            # Command generation: _render_commands, _render_caddy_dstnat
└── helpers.py           # Utilities: _normalize_ports_lenient, _to_bool, etc.
```

**Benefits**:
- Each file is 150-300 lines (easily readable in one screen)
- Clear separation of concerns
- Easy to test `data.py` functions without invoking UI
- Can mock `ui.py` for automated testing
- New contributors can understand one piece at a time

### Example: `deploy` → `homelab/deploy/`

```
homelab/deploy/
├── __init__.py          # Public API: main() function
├── __main__.py          # Enable `python -m deploy`
├── nodes.py             # Node config extraction from sheets
├── ansible.py           # Ansible playbook execution and orchestration
├── ssh.py               # SSH operations and helper script deployment
└── config.py            # TOML parsing and validation
```

### Example: `caddyfile` → `homelab/caddy/`

```
homelab/caddy/
├── __init__.py          # Public API: main() function
├── __main__.py          # Enable `python -m caddy`
├── sheets.py            # Sheet loading and service/node extraction
├── conflicts.py         # Port and domain conflict detection
├── render.py            # Caddyfile template rendering
└── models.py            # Data classes for services, routes, zones
```

## Migration Strategy

### Step 1: Create Package Structure

```bash
mkdir -p homelab/mikrotik
touch homelab/mikrotik/{__init__,__main__,data,models,ui,render,helpers}.py
```

### Step 2: Move Code by Logical Group

**models.py** gets all dataclasses:
```python
# Move ServiceFormData, ParsedInput
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class ServiceFormData:
    ...
```

**data.py** gets all sheet loading functions:
```python
# Move _load_sheet_df, _prefill_from_services_sheet, etc.
from ..sheets import get_sheet_df, build_sheet_url
```

**ui.py** gets all interactive prompts:
```python
# Move _run_form_ui, _run_confirmation_ui, _run_service_selection_menu
from .models import ServiceFormData
```

**render.py** gets command generation:
```python
# Move _render_commands, _render_caddy_dstnat
from .models import ParsedInput
```

**helpers.py** gets utility functions:
```python
# Move _normalize_ports_lenient, _to_bool, _generate_random_mac
```

### Step 3: Wire Up __init__.py

```python
"""MikroTik service configuration generator."""
from .ui import _run_form_ui, _run_confirmation_ui
from .data import _prefill_from_services_sheet, _prefill_from_nodes_sheet
from .render import _render_commands
from .models import ServiceFormData, ParsedInput
from .helpers import _normalize_form

def main(argv: list[str] | None = None) -> int:
    # Original main() logic, now importing from submodules
    ...
```

### Step 4: Create __main__.py

```python
"""Entry point for `python -m mikrotik`."""
from . import main

if __name__ == "__main__":
    raise SystemExit(main())
```

### Step 5: Update Top-Level Wrapper

`mikrotik.py` at repo root stays the same:
```python
from homelab.mikrotik import main

# ... delegates to main()
```

## Testing Strategy

1. **Before refactoring**: Run existing CLI commands and save output
2. **After refactoring**: Run same commands and compare output (should be identical)
3. **Syntax check**: `python3 -m py_compile homelab/mikrotik/*.py`
4. **Import check**: `python3 -c "from homelab import mikrotik; print(mikrotik.main)"`

## Backward Compatibility

- **Public API unchanged**: `from homelab.mikrotik_prompt import main` still works if we keep the old module as a thin wrapper
- **CLI unchanged**: `python -m mikrotik` and `python -m homelab mikrotik` both work
- **Config unchanged**: No TOML changes required

## Implementation Plan

### Phase 1 (This PR)
- [x] Document decomposition strategy
- [ ] Split `mikrotik_prompt` into `homelab/mikrotik/` package
- [ ] Add unit tests for extracted modules

### Phase 2 (Future PR)
- [ ] Split `deploy.py` into `homelab/deploy/` package
- [ ] Split `caddyfile.py` into `homelab/caddy/` package
- [ ] Split `pihole.py` into `homelab/pihole/` package (if it grows further)

### Phase 3 (Future PR)
- [ ] Add `pytest` test suite for all packages
- [ ] Add type checking with `mypy --strict`
- [ ] Add coverage reporting

## Benefits Summary

1. **Readability**: 200-line files vs 1400-line files
2. **Testability**: Mock UI for data/render testing
3. **Maintainability**: Change one concern without touching others
4. **Onboarding**: New contributors can understand one submodule at a time
5. **Reusability**: `data.py` functions could be used by other tools

## Files Changed (This PR)

- `docs/pr-3-module-decomposition.md` (this document)
- TODO: Actual decomposition commits will follow

---

**Part of homelab refactoring series**: PR #3 of 4, establishing package-based architecture for large modules.
