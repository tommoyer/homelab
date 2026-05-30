from __future__ import annotations

import curses
import sys
from dataclasses import dataclass
from typing import Callable

from .cli_common import SENTINEL_APPLY, SENTINEL_DEBUG, SENTINEL_KEEP
from .commands import COMMANDS
from .sheets import clear_sheet_df_cache


@dataclass
class GlobalFlags:
    """Global flags that apply to all commands."""
    debug: bool = False
    apply: bool = False
    keep: bool = False


@dataclass(frozen=True)
class MenuEntry:
    name: str
    description: str
    runner: Callable[[list[str] | None], int]


def _build_menu_entries() -> list[MenuEntry]:
    """Build menu entries from registered commands."""
    entries: list[MenuEntry] = []
    for name, (description, module) in COMMANDS.items():
        if name == "run":
            continue
        if module is None or not hasattr(module, "main"):
            continue

        def make_runner(mod: object) -> Callable[[list[str] | None], int]:
            def _run(argv: list[str] | None = None) -> int:
                if argv is None:
                    argv = []
                return int(mod.main(argv))  # type: ignore[attr-defined]
            return _run

        entries.append(
            MenuEntry(
                name=name,
                description=description,
                runner=make_runner(module),
            )
        )

    def _reload_sheets_cache(_argv: list[str] | None = None) -> int:
        clear_sheet_df_cache()
        print("Google Sheets cache cleared. Next run will fetch fresh data.")
        return 0

    entries.append(
        MenuEntry(
            name="reload_sheets",
            description="Clear cached Google Sheets data",
            runner=_reload_sheets_cache,
        )
    )

    entries.sort(key=lambda e: e.name)
    return entries


def _main_menu(
    stdscr: "curses._CursesWindow",  # type: ignore[name-defined]
    entries: list[MenuEntry],
    global_flags: GlobalFlags
) -> MenuEntry | None:
    """Display main command selection menu with global flags."""
    curses.curs_set(0)
    
    # 0 = debug flag, 1 = apply flag, 2 = keep flag, 3+ = commands
    num_global_items = 3
    selected = num_global_items  # Start on first command by default

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        stdscr.addstr(0, 0, "═" * min(width - 1, 80))
        stdscr.addstr(1, 0, "  HOMELAB TOOLS MENU")
        stdscr.addstr(2, 0, "═" * min(width - 1, 80))
        stdscr.addstr(3, 0, "Use ↑/↓ to select, Space to toggle flags, Enter to run, q to quit")
        stdscr.addstr(4, 0, "─" * min(width - 1, 80))
        
        # Global flags section
        y = 6
        stdscr.addstr(y, 0, "Global Flags:")
        y += 1
        
        # Debug flag
        prefix = "▶" if selected == 0 else " "
        debug_toggle = "[×]" if global_flags.debug else "[ ]"
        stdscr.addstr(y, 0, f"{prefix} {debug_toggle} --debug         Enable verbose debug logging")
        y += 1
        
        # Apply flag
        prefix = "▶" if selected == 1 else " "
        apply_toggle = "[×]" if global_flags.apply else "[ ]"
        apply_label = (
            f"{prefix} {apply_toggle} --apply         "
            "Apply changes (deploy, dns, caddy)"
        )
        stdscr.addstr(y, 0, apply_label)
        y += 1

        # Keep flag
        prefix = "▶" if selected == 2 else " "
        keep_toggle = "[×]" if global_flags.keep else "[ ]"
        keep_label = (
            f"{prefix} {keep_toggle} --keep          "
            "Keep downloaded Sheets CSVs for debugging"
        )
        stdscr.addstr(y, 0, keep_label)
        y += 1
        
        stdscr.addstr(y, 0, "─" * min(width - 1, 80))
        y += 1
        stdscr.addstr(y, 0, "Commands:")
        y += 1

        # Command list
        for idx, entry in enumerate(entries):
            cmd_selected = selected - num_global_items
            prefix = "▶" if idx == cmd_selected else " "
            label = f"{prefix} {entry.name.ljust(16)}  {entry.description}"
            if y < height - 1:
                stdscr.addstr(y, 0, label[: width - 1])
            y += 1

        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q"), 27):  # q, Q, or ESC
            return None
        if ch == curses.KEY_UP:
            selected = (selected - 1) % (len(entries) + num_global_items)
        elif ch == curses.KEY_DOWN:
            selected = (selected + 1) % (len(entries) + num_global_items)
        elif ch == ord(" "):  # Space to toggle global flags
            if selected == 0:  # Debug flag
                global_flags.debug = not global_flags.debug
            elif selected == 1:  # Apply flag
                global_flags.apply = not global_flags.apply
            elif selected == 2:  # Keep flag
                global_flags.keep = not global_flags.keep
        elif ch in (10, 13, curses.KEY_ENTER):  # Enter
            if selected >= num_global_items:
                # Selected a command
                return entries[selected - num_global_items]


def main(argv: list[str] | None = None) -> int:
    """Launch the homelab TUI."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "Error: homelab TUI requires an interactive terminal (stdin/stdout must be a TTY).",
            file=sys.stderr,
        )
        return 2

    entries = _build_menu_entries()
    if not entries:
        print("Error: no homelab commands are available for the TUI menu.", file=sys.stderr)
        return 1

    # Global flags persist across menu iterations
    global_flags = GlobalFlags()

    # Main loop: select command -> configure -> run -> back to menu
    while True:
        selected_entry = curses.wrapper(lambda stdscr: _main_menu(stdscr, entries, global_flags))
        if selected_entry is None:
            # User quit
            return 0

        command_argv: list[str] = []
        
        # Add global flags for commands that support them.
        if global_flags.debug and SENTINEL_DEBUG not in command_argv:
            if selected_entry.name in {"caddy", "mikrotik", "deploy", "dns", "tailscale_install", "update"}:
                command_argv.insert(0, SENTINEL_DEBUG)
        
        if global_flags.apply and SENTINEL_APPLY not in command_argv:
            if selected_entry.name in {"deploy", "dns", "caddy", "tailscale_install", "update"}:
                command_argv.insert(0, SENTINEL_APPLY)

        if global_flags.keep and SENTINEL_KEEP not in command_argv:
            if selected_entry.name in {"deploy", "dns", "caddy", "tailscale_install", "mikrotik", "update"}:
                command_argv.insert(0, SENTINEL_KEEP)
        
        print(f"\n{'═' * 60}")
        print(f"Running: {selected_entry.name} {' '.join(command_argv)}")
        print(f"{'═' * 60}\n")
        
        try:
            exit_code = selected_entry.runner(command_argv)
            print(f"\n{'─' * 60}")
            print(f"Command exited with code: {exit_code}")
            print(f"{'─' * 60}")
        except KeyboardInterrupt:
            print("\n\nAborted by user (Ctrl+C)", file=sys.stderr)
            exit_code = 130
        except Exception as exc:
            print(f"\n\nError: {exc}", file=sys.stderr)
            exit_code = 1
        
        # Wait for user before returning to menu
        try:
            input("\nPress Enter to return to menu...")
        except (KeyboardInterrupt, EOFError):
            # User pressed Ctrl+C or Ctrl+D, just return to menu
            print()  # New line for cleaner output
            pass
