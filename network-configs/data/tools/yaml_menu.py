#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency fallback
    yaml = None

YAML_SUFFIXES = (".yaml", ".yml")
DIR_KEY_MAP = {
    "assets": "assets",
    "services": "services",
    "dns-names": "dns_names",
}
ID_FIELD_MAP = {
    "vlans": "vlan_id",
    "assets": "asset_id",
    "services": "service_id",
    "dns_names": "dns_id",
}


def is_yaml_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in YAML_SUFFIXES


def dir_has_yaml_files(path: Path) -> bool:
    try:
        return any(is_yaml_file(child) for child in path.iterdir())
    except FileNotFoundError:
        return False


def scan_root(base_dir: Path) -> tuple[list[Path], list[Path]]:
    top_files = sorted([p for p in base_dir.iterdir() if is_yaml_file(p)])
    dirs = sorted([p for p in base_dir.iterdir() if p.is_dir() and dir_has_yaml_files(p)])
    return top_files, dirs


def read_input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return "q"


def prompt_choice(title: str, options: list[str], allow_back: bool, allow_quit: bool) -> tuple[str, int | None]:
    print()
    print(title)
    for idx, label in enumerate(options, start=1):
        print(f"{idx}) {label}")
    if allow_back:
        print("b) back")
    if allow_quit:
        print("q) quit")
    while True:
        choice = read_input("> ").strip().lower()
        if allow_quit and choice in ("q", "quit"):
            return "quit", None
        if allow_back and choice in ("b", "back"):
            return "back", None
        if choice.isdigit():
            value = int(choice)
            if 1 <= value <= len(options):
                return "item", value - 1
        print("Invalid choice. Try again.")


def editor_command() -> list[str]:
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    return shlex.split(editor)


def open_in_editor(path: Path) -> None:
    cmd = editor_command() + [str(path)]
    subprocess.run(cmd, check=False)


def view_file(path: Path) -> None:
    print()
    print(f"--- {path} ---")
    try:
        with path.open("r", encoding="utf-8") as handle:
            for idx, line in enumerate(handle, start=1):
                print(f"{idx:4d} | {line.rstrip()}")
    except FileNotFoundError:
        print("File not found.")
    print("--- end ---")


def list_yaml_files(path: Path) -> list[Path]:
    files = [p for p in path.iterdir() if is_yaml_file(p)]
    return sorted(files, key=lambda p: p.name.lower())


def load_yaml(path: Path) -> object | None:
    if yaml is None:
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except (FileNotFoundError, PermissionError, OSError, yaml.YAMLError):
        return None


def extract_ids_from_data(data: object, kind_key: str | None) -> list[str]:
    if not isinstance(data, (dict, list)):
        return []
    id_field = ID_FIELD_MAP.get(kind_key) if kind_key else None
    items = None
    if isinstance(data, dict):
        if kind_key and kind_key in data:
            items = data.get(kind_key)
        else:
            for key, field in ID_FIELD_MAP.items():
                if key in data:
                    items = data.get(key)
                    id_field = field
                    break
    if items is None:
        items = data
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []
    ids: list[str] = []
    for item in items:
        if isinstance(item, dict) and id_field in item:
            value = item.get(id_field)
            if isinstance(value, str) and value:
                ids.append(value)
    return ids


def format_id_label(ids: list[str]) -> str:
    if not ids:
        return ""
    if len(ids) <= 3:
        return ", ".join(ids)
    return f"{', '.join(ids[:3])} (+{len(ids) - 3})"


def file_label(path: Path, kind_key: str | None) -> str:
    data = load_yaml(path)
    ids = extract_ids_from_data(data, kind_key) if data is not None else []
    label = format_id_label(ids)
    return label or path.name


def new_file_template(dir_name: str, mode: str) -> str:
    key = DIR_KEY_MAP.get(dir_name)
    if mode == "blank":
        return ""
    if mode == "empty_list":
        if key:
            return f"schema_version: 1\n{key}: []\n"
        return "[]\n"
    if mode == "single_item":
        if key:
            return f"schema_version: 1\n{key}:\n- {{}}\n"
        return "- {}\n"
    return ""


def create_new_file(dir_path: Path) -> None:
    print()
    name = read_input("New file name (without path): ").strip()
    if not name:
        print("Cancelled.")
        return
    if "/" in name or "\\" in name:
        print("Invalid name: file names only.")
        return
    if not name.lower().endswith(YAML_SUFFIXES):
        name = f"{name}.yaml"
    new_path = dir_path / name
    if new_path.exists():
        print(f"{new_path} already exists.")
        return

    template_options = [
        "Empty list for this type (schema_version + key)",
        "Single empty item for this type (schema_version + key)",
        "Blank file",
        "Copy from existing file",
    ]
    action, idx = prompt_choice("Choose a template:", template_options, allow_back=True, allow_quit=False)
    if action != "item":
        print("Cancelled.")
        return

    content = ""
    if idx == 3:
        existing_files = list_yaml_files(dir_path)
        if not existing_files:
            print("No files available to copy.")
            return
        kind_key = DIR_KEY_MAP.get(dir_path.name)
        labels = [file_label(p, kind_key) for p in existing_files]
        action, file_idx = prompt_choice("Copy which file?", labels, allow_back=True, allow_quit=False)
        if action != "item":
            print("Cancelled.")
            return
        content = existing_files[file_idx].read_text(encoding="utf-8")
    else:
        mode_map = {0: "empty_list", 1: "single_item", 2: "blank"}
        content = new_file_template(dir_path.name, mode_map[idx])

    new_path.write_text(content, encoding="utf-8")
    print(f"Created {new_path}")
    should_edit = read_input("Open in editor now? [y/N]: ").strip().lower()
    if should_edit in ("y", "yes"):
        open_in_editor(new_path)


def file_menu(path: Path) -> None:
    while True:
        options = ["View", "Edit", "Back"]
        action, idx = prompt_choice(f"File: {path.name}", options, allow_back=False, allow_quit=True)
        if action == "quit":
            sys.exit(0)
        if action != "item":
            continue
        if idx == 0:
            view_file(path)
        elif idx == 1:
            open_in_editor(path)
        else:
            return


def directory_menu(path: Path) -> None:
    while True:
        files = list_yaml_files(path)
        kind_key = DIR_KEY_MAP.get(path.name)
        options = [file_label(p, kind_key) for p in files] + ["Add new file"]
        action, idx = prompt_choice(f"Directory: {path.name}", options, allow_back=True, allow_quit=True)
        if action == "quit":
            sys.exit(0)
        if action == "back":
            return
        if action != "item":
            continue
        if idx == len(options) - 1:
            create_new_file(path)
        else:
            file_menu(files[idx])


def root_menu(base_dir: Path) -> None:
    while True:
        top_files, dirs = scan_root(base_dir)
        top_labels = []
        for path in top_files:
            label = file_label(path, None)
            top_labels.append(f"{label} (file)")
        options = top_labels + [f"{p.name}/ (dir)" for p in dirs]
        action, idx = prompt_choice(f"Base: {base_dir}", options, allow_back=False, allow_quit=True)
        if action == "quit":
            return
        if action != "item":
            continue
        if idx < len(top_files):
            file_menu(top_files[idx])
        else:
            directory_menu(dirs[idx - len(top_files)])


def main() -> int:
    parser = argparse.ArgumentParser(description="Menu-driven viewer/editor for network YAML files.")
    parser.add_argument(
        "--base",
        default=Path(__file__).resolve().parents[1],
        type=Path,
        help="Base data directory (default: network-configs/data)",
    )
    args = parser.parse_args()
    base_dir = args.base.expanduser().resolve()
    if not base_dir.exists():
        print(f"Base directory not found: {base_dir}")
        return 1
    if not base_dir.is_dir():
        print(f"Base path is not a directory: {base_dir}")
        return 1
    root_menu(base_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
