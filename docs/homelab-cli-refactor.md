# homelab CLI refactor notes

This document describes the refactor of the `homelab` Python package to make the
codebase more modular and easier to reuse from both the command line and
higher‑level UIs.

## Goals

- Centralise shared behaviour (config loading, Sheets helpers, command
  registry) into reusable library modules.
- Allow each major tool to be run directly as a top‑level module, e.g.
  `python -m mikrotik`, without going through `python -m homelab`.
- Introduce a very thin ncurses menu that can launch any of the tools without
  changing their existing CLIs or behaviour.

## Shared command registry

A new module `homelab/commands.py` defines a single `COMMANDS` mapping that
associates each command name with its human‑readable description and the module
implementing it. This replaces the ad‑hoc dictionary that previously lived
inside `homelab/cli.py` so both the unified CLI and the ncurses menu share the
same source of truth.

```python
from . import caddyfile, deploy, dnscontrol, mikrotik_prompt, pihole, subnet_assign

COMMANDS: dict[str, tuple[str, object]] = {
    "run": ("Run multiple features", object()),
    "pihole": ("Generate/apply Pi-hole config", pihole),
    "dnscontrol": ("Generate dnscontrol files for Cloudflare public DNS", dnscontrol),
    "mikrotik": ("Prompt-driven single-service MikroTik command generator", mikrotik_prompt),
    "caddy": ("Generate/deploy Caddyfile from Google Sheets", caddyfile),
    "deploy": ("Deploy a complete node/service", deploy),
    "subnet_assign": ("Interactive subnet/IP assignment tool", subnet_assign),
}
```

`homelab.cli` now imports this mapping and uses it both for help text and for
subcommand dispatch. The special `run` pseudo‑command remains orchestrated by
`homelab.cli` because it needs custom argument plumbing and error handling
across multiple tools.

## Unified CLI (`python -m homelab`)

`homelab/cli.py` has been simplified to:

- Use the shared `COMMANDS` registry for listing commands and dispatching to
  modules.
- Keep the existing global `--debug` flag and "run" orchestration logic.
- Call each subcommand’s `main(argv)` function via the module stored in
  `COMMANDS` rather than importing those modules directly.

This keeps the unified CLI behaviour unchanged while making it easier to reuse
command metadata elsewhere (like the ncurses menu).

## Stand‑alone CLI entrypoints

To make each tool runnable as its own top‑level module, thin wrapper modules
have been added at the repository root:

- `mikrotik.py` → `homelab.mikrotik_prompt.main`
- `pihole.py` → `homelab.pihole.main`
- `dnscontrol.py` → `homelab.dnscontrol.main`
- `caddy.py` → `homelab.caddyfile.main`
- `deploy.py` → `homelab.deploy.main`
- `subnet_assign.py` → `homelab.subnet_assign.main`

Each wrapper follows the same pattern:

```python
from homelab import pihole as _pihole


def main(argv: list[str] | None = None) -> int:
    return int(_pihole.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
```

This means you can now invoke tools directly with:

- `python -m mikrotik ...`
- `python -m pihole ...`
- `python -m dnscontrol ...`
- `python -m caddy ...`
- `python -m deploy ...`
- `python -m subnet_assign ...`

while the existing `python -m homelab <command> ...` flow continues to work as
before.

## Ncurses menu (`python -m homelab_ui`)

A thin ncurses UI has been added in `homelab/ui.py` with a top‑level wrapper
module `homelab_ui.py`.

- The menu is built dynamically from `homelab.commands.COMMANDS`, skipping the
  orchestration‑only `run` pseudo‑command.
- The UI presents a scrollable list of commands with their descriptions
  (sourced from the registry) and lets the user select one with the arrow keys
  and Enter.
- When the user chooses a command, the TUI exits and calls the underlying
  module’s `main([])` function. For now it intentionally does not plumb extra
  arguments; the expectation is that advanced usage continues to go through the
  dedicated CLIs.

Invocation examples:

- `python -m homelab_ui` – open the ncurses menu and choose a tool.
- `python -m mikrotik` – run the MikroTik prompt tool directly.
- `python -m homelab mikrotik` – legacy invocation, still supported.

The curses UI is deliberately conservative: it avoids trying to nest other
curses UIs inside itself and exits the menu before running tools such as the
MikroTik prompt that already manage their own full‑screen terminal experience.

## Future improvements / ideas

- Factor additional shared CLI plumbing (e.g. common `--config` parsing,
  logging configuration, and Google Sheets URL handling) into a `homelab.cli_
  common` module and update individual tools to use it.
- Add optional argument editing within the TUI so a user can, for example,
  toggle `--apply` for pihole or dnscontrol from the menu before launching.
- Create dedicated console entry points (via `pyproject.toml` or `setup.cfg`)
  so commands like `homelab-mikrotik` can be installed into a virtualenv and
  used without spelling out `python -m`.
