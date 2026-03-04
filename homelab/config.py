from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
    logger.debug("merge_config_tables: keys=%s", sorted(merged.keys()))
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

    effective = merge_config_tables(globals_cfg, *inherited, section_cfg)
    logger.debug(
        "get_effective_table: section=%s inherit=%s legacy_root_fallback=%s keys=%s",
        section,
        inherit,
        legacy_root_fallback,
        sorted(effective.keys()),
    )
    return effective


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
    resolved = path.resolve()
    logger.debug("resolve_path_relative_to_config: %s -> %s", value, resolved)
    return resolved


def load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file into a dict.

    Returns {} when the file does not exist.

    Raises RuntimeError on parse errors.
    """

    if not path.exists():
        logger.debug("load_toml: missing file: %s", path)
        return {}

    logger.debug("load_toml: reading file: %s", path)

    try:
        import tomllib  # py3.11+

        with path.open("rb") as handle:
            data = tomllib.load(handle)
            logger.debug("load_toml: loaded keys=%s", sorted(data.keys()))
            return data
    except ModuleNotFoundError:
        pass

    try:
        import toml

        data = toml.load(path)
        logger.debug("load_toml: loaded keys=%s", sorted(data.keys()))
        return data
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


DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1f4emn4uIPscEgOHtgmETODlTvz1eh2xZlnpBBNGQlWA/"
    "export?format=csv&gid=0"
)


def pre_parse_config(argv: list[str] | None = None) -> tuple[Path, dict[str, Any]]:
    """Pre-parse --config from argv and load the TOML config file.

    Every tool module duplicated this exact pattern; this centralises it.
    Returns (config_path, config_dict).
    """

    default_config = Path.cwd().resolve() / "config.toml"
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "--config",
        type=Path,
        default=default_config,
        help="Path to TOML config file containing default parameters",
    )
    pre_args, _ = pre_parser.parse_known_args(argv)
    config_path = pre_args.config.expanduser().resolve()
    config = load_toml_or_exit(config_path)
    logger.debug("pre_parse_config: path=%s keys=%s", config_path, sorted(config.keys()))
    return config_path, config


def render_jinja_template(*, template_path: Path, context: dict[str, Any]) -> str:
    """Render a Jinja2 template file with the given context dict."""

    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_path.name)
    return str(template.render(**context))


def is_unified_mikrotik_config(config: dict[str, Any]) -> bool:
    """Return True if config uses the unified mikrotik_* section layout."""

    return any(
        isinstance(config.get(key), dict)
        for key in ("mikrotik_defaults", "mikrotik_dhcp_leases", "mikrotik_firewall", "mikrotik_backup")
    )
