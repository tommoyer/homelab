from __future__ import annotations

import curses
import sys
from dataclasses import dataclass
from typing import Callable

from .commands import COMMANDS


@dataclass(frozen=True)
class MenuEntry:
    name: str
    description: str
    runner: Callable[[list[str] | None], int]


def _build_menu_entries() -> list[MenuEntry]:
    entries: list[MenuEntry] = []
    for name, (description, module) in COMMANDS.items():
        if name == "run":
            # The run pseudo-command is orchestration-only; keep the TUI focused
            # on concrete tools.
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


def _menu(stdscr: "curses._CursesWindow", entries: list[MenuEntry]) -> MenuEntry | None:  # type: ignore[name-defined]
    curses.curs_set(0)
    selected = 0

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        title = "homelab tools menu"
        stdscr.addstr(0, 0, title[: max(1, width - 1)])
        stdscr.addstr(1, 0, "Use ↑/↓ to select, Enter to run, q to quit"[: max(1, width - 1)])

        for idx, entry in enumerate(entries):
            prefix = ">" if idx == selected else " "
            label = f"{prefix} {entry.name.ljust(14)}  {entry.description}"
            stdscr.addstr(3 + idx, 0, label[: max(1, width - 1)])

        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")):
            return None
        if ch == curses.KEY_UP:
            selected = (selected - 1) % len(entries)
            continue
        if ch == curses.KEY_DOWN:
            selected = (selected + 1) % len(entries)
            continue
        if ch in (10, 13):
            return entries[selected]


def main(argv: list[str] | None = None) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Error: homelab TUI requires an interactive terminal (stdin/stdout must be a TTY).", file=sys.stderr)
        return 2

    entries = _build_menu_entries()
    if not entries:
        print("Error: no homelab commands are available for the TUI menu.", file=sys.stderr)
        return 1

    selected = curses.wrapper(lambda stdscr: _menu(stdscr, entries))
    if selected is None:
        return 0

    # For now we ignore any extra argv beyond the program name inside the TUI
    # and always invoke subcommands with an empty argument list. This keeps the
    # UI intentionally thin; callers can still use the dedicated CLIs directly
    # when they need advanced flags.
    try:
        return selected.runner([])
    except KeyboardInterrupt:
        print("Aborted", file=sys.stderr)
        return 130
