from __future__ import annotations

import argparse
import curses
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from .commands import COMMANDS


@dataclass(frozen=True)
class MenuEntry:
    name: str
    description: str
    runner: Callable[[list[str] | None], int]


@dataclass
class FlagConfig:
    """Configuration for a command-line flag that can be toggled in the TUI."""
    name: str                    # e.g., "--apply"
    description: str             # Help text
    flag_type: str              # "bool", "string", "choice"
    default: Any = None
    choices: list[str] | None = None
    enabled: bool = False        # Current toggle state (for bools)
    value: str | None = None    # Current value (for strings/choices)


@dataclass
class CommandConfig:
    """Configuration state for a single command before execution."""
    entry: MenuEntry
    flags: list[FlagConfig] = field(default_factory=list)


def _discover_flags(command_name: str, module: object) -> list[FlagConfig]:
    """Discover configurable flags from a command's argument parser.
    
    This introspects the module's build_parser or argument setup to extract
    high-value flags that should be exposed in the TUI.
    """
    # Common flags we want to expose across tools
    known_flags = {
        "--apply": FlagConfig(
            name="--apply",
            description="Apply changes to remote host",
            flag_type="bool",
            default=False,
        ),
        "--debug": FlagConfig(
            name="--debug",
            description="Enable debug logging",
            flag_type="bool",
            default=False,
        ),
        "--sudo": FlagConfig(
            name="--sudo",
            description="Use sudo when applying",
            flag_type="bool",
            default=False,
        ),
        "--tailnet": FlagConfig(
            name="--tailnet",
            description="Tailscale tailnet domain",
            flag_type="string",
            default="",
        ),
    }
    
    # Map commands to their relevant flags
    command_flag_map = {
        "pihole": ["--apply", "--debug", "--sudo", "--tailnet"],
        "dnscontrol": ["--apply", "--debug"],
        "caddy": ["--apply", "--debug"],
        "deploy": ["--debug"],
        "mikrotik": ["--debug"],
        "subnet_assign": [],
    }
    
    flags = []
    for flag_name in command_flag_map.get(command_name, []):
        if flag_name in known_flags:
            # Create a fresh copy so each command has independent state
            base = known_flags[flag_name]
            flags.append(FlagConfig(
                name=base.name,
                description=base.description,
                flag_type=base.flag_type,
                default=base.default,
                choices=base.choices,
                enabled=base.enabled,
                value=base.value,
            ))
    
    return flags


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

    entries.sort(key=lambda e: e.name)
    return entries


def _main_menu(
    stdscr: "curses._CursesWindow",  # type: ignore[name-defined]
    entries: list[MenuEntry]
) -> MenuEntry | None:
    """Display main command selection menu."""
    curses.curs_set(0)
    selected = 0

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        stdscr.addstr(0, 0, "═" * min(width - 1, 80))
        stdscr.addstr(1, 0, "  HOMELAB TOOLS MENU")
        stdscr.addstr(2, 0, "═" * min(width - 1, 80))
        stdscr.addstr(3, 0, "Use ↑/↓ to select, Enter to configure/run, q to quit")
        stdscr.addstr(4, 0, "─" * min(width - 1, 80))

        for idx, entry in enumerate(entries):
            prefix = "▶" if idx == selected else " "
            label = f"{prefix} {entry.name.ljust(16)}  {entry.description}"
            y_pos = 6 + idx
            if y_pos < height - 1:
                stdscr.addstr(y_pos, 0, label[: width - 1])

        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q"), 27):  # q, Q, or ESC
            return None
        if ch == curses.KEY_UP:
            selected = (selected - 1) % len(entries)
        elif ch == curses.KEY_DOWN:
            selected = (selected + 1) % len(entries)
        elif ch in (10, 13, curses.KEY_ENTER):  # Enter
            return entries[selected]


def _config_menu(
    stdscr: "curses._CursesWindow",  # type: ignore[name-defined]
    config: CommandConfig
) -> bool:
    """Display configuration menu for a command. Returns True to run, False to cancel."""
    curses.curs_set(0)
    selected = 0
    
    # If no flags, just run immediately
    if not config.flags:
        return True
    
    # Add "Run" and "Cancel" options
    num_items = len(config.flags) + 2
    
    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        stdscr.addstr(0, 0, "═" * min(width - 1, 80))
        stdscr.addstr(1, 0, f"  Configure: {config.entry.name}")
        stdscr.addstr(2, 0, "═" * min(width - 1, 80))
        stdscr.addstr(3, 0, "Use ↑/↓ to select, Space to toggle, Enter to confirm")
        stdscr.addstr(4, 0, "─" * min(width - 1, 80))
        
        y = 6
        
        # Display flags
        for idx, flag in enumerate(config.flags):
            prefix = "▶" if idx == selected else " "
            
            if flag.flag_type == "bool":
                toggle = "[×]" if flag.enabled else "[ ]"
                label = f"{prefix} {toggle} {flag.name.ljust(16)}  {flag.description}"
            elif flag.flag_type == "string":
                value_display = f'"{flag.value}"' if flag.value else "<empty>"
                label = f"{prefix}     {flag.name.ljust(16)}  {value_display}"
            else:
                label = f"{prefix}     {flag.name.ljust(16)}  {flag.description}"
            
            if y < height - 4:
                stdscr.addstr(y, 0, label[: width - 1])
            y += 1
        
        # Add separator
        if y < height - 3:
            stdscr.addstr(y, 0, "─" * min(width - 1, 80))
        y += 1
        
        # Run option
        run_idx = len(config.flags)
        prefix = "▶" if selected == run_idx else " "
        if y < height - 2:
            stdscr.addstr(y, 0, f"{prefix} [Run Command]"[: width - 1])
        y += 1
        
        # Cancel option
        cancel_idx = len(config.flags) + 1
        prefix = "▶" if selected == cancel_idx else " "
        if y < height - 1:
            stdscr.addstr(y, 0, f"{prefix} [Cancel]"[: width - 1])
        
        ch = stdscr.getch()
        
        if ch in (ord("q"), ord("Q"), 27):  # q, Q, or ESC
            return False
        elif ch == curses.KEY_UP:
            selected = (selected - 1) % num_items
        elif ch == curses.KEY_DOWN:
            selected = (selected + 1) % num_items
        elif ch == ord(" "):  # Space to toggle
            if selected < len(config.flags):
                flag = config.flags[selected]
                if flag.flag_type == "bool":
                    # Toggle boolean flag
                    config.flags[selected] = FlagConfig(
                        name=flag.name,
                        description=flag.description,
                        flag_type=flag.flag_type,
                        default=flag.default,
                        choices=flag.choices,
                        enabled=not flag.enabled,
                        value=flag.value,
                    )
        elif ch in (10, 13, curses.KEY_ENTER):  # Enter
            if selected == run_idx:
                return True
            elif selected == cancel_idx:
                return False


def _build_argv_from_config(config: CommandConfig) -> list[str]:
    """Build argv list from command configuration."""
    argv = []
    for flag in config.flags:
        if flag.flag_type == "bool" and flag.enabled:
            argv.append(flag.name)
        elif flag.flag_type == "string" and flag.value:
            argv.extend([flag.name, flag.value])
    return argv


def main(argv: list[str] | None = None) -> int:
    """Launch the enhanced homelab TUI with per-command configuration."""
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

    # Main loop: select command -> configure -> run -> back to menu
    while True:
        selected_entry = curses.wrapper(lambda stdscr: _main_menu(stdscr, entries))
        if selected_entry is None:
            # User quit
            return 0
        
        # Discover flags for the selected command
        command_module = None
        for name, (_, module) in COMMANDS.items():
            if name == selected_entry.name:
                command_module = module
                break
        
        flags = _discover_flags(selected_entry.name, command_module)
        config = CommandConfig(entry=selected_entry, flags=flags)
        
        # Show configuration menu
        should_run = curses.wrapper(lambda stdscr: _config_menu(stdscr, config))
        if not should_run:
            # User cancelled, go back to main menu
            continue
        
        # Build argv and run the command
        command_argv = _build_argv_from_config(config)
        
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
