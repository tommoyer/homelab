from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def merge_config_tables(*tables: Any) -> dict[str, Any]:
    """Shallow-merge TOML tables (dict-like objects).

    Later tables win. Keys with value None are ignored (treated as unset).
    """

    merged: dict[str, Any] = {}
    for table in tables:
        for key, value in _as_dict(table).items():
            if value is None:
                continue
            merged[key] = value
    return merged


def get_table(config: dict[str, Any], key: str) -> dict[str, Any]:
    """Return config[key] if it's a TOML table, else {}."""

    return _as_dict(config.get(key, {}))


def get_effective_table(
    config: dict[str, Any],
    section: str,
    *,
    inherit: tuple[str, ...] = (),
    legacy_root_fallback: bool = False,
) -> dict[str, Any]:
    """Return an effective table for a tool section.

    Merge order:
      1) [globals]
      2) any inherited tables (in order)
      3) [<section>]

    If legacy_root_fallback is True and [<section>] is missing/not a table,
    the root config is treated as the section table for backward compatibility.
    """

    globals_cfg = get_table(config, "globals")
    inherited = [get_table(config, name) for name in inherit]

    section_value = config.get(section, None)
    if isinstance(section_value, dict):
        section_cfg: dict[str, Any] = section_value
    elif legacy_root_fallback:
        section_cfg = config
    else:
        section_cfg = {}

    return merge_config_tables(globals_cfg, *inherited, section_cfg)


def resolve_path_relative_to_config(config_path: Path, value: str | Path) -> Path:
    """Resolve a path from a config value.

    - Expands '~'
    - If the path is relative, treats it as relative to config_path.parent
    - Returns an absolute, normalized path
    """

    raw = value
    path = raw if isinstance(raw, Path) else Path(str(raw))
    path = path.expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file into a dict.

    Returns {} when the file does not exist.

    Raises RuntimeError on parse errors.
    """

    if not path.exists():
        return {}

    try:
        import tomllib  # py3.11+

        with path.open("rb") as handle:
            return tomllib.load(handle)
    except ModuleNotFoundError:
        pass

    try:
        import toml

        return toml.load(path)
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"failed to parse config file {path}: {exc}") from exc


def load_toml_or_exit(path: Path) -> dict[str, Any]:
    try:
        return load_toml(path)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


def get_config_value(config: dict[str, Any], key: str, default: Any) -> Any:
    value = config.get(key, default)
    return default if value is None else value
