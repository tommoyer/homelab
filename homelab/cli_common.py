"""Common CLI utilities for homelab tools.

This module centralizes repetitive CLI patterns: config parsing, parser building,
debug/logging bootstrap, and common argument handling.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from .config import get_config_value, get_table, load_toml_or_exit, pre_parse_config
from .logging_utils import configure_logging

logger = logging.getLogger(__name__)


def add_config_argument(
    parser: argparse.ArgumentParser,
    config_path: Path | None = None,
    help_text: str = "Path to TOML config file containing default parameters",
) -> None:
    """Add standard --config argument to parser.

    Args:
        parser: ArgumentParser instance to modify
        config_path: Default config path (typically from pre_parse_config)
        help_text: Help text for the --config argument
    """
    parser.add_argument(
        "--config",
        type=Path,
        default=config_path,
        help=help_text,
    )


def add_debug_argument(
    parser: argparse.ArgumentParser,
    default: bool = False,
) -> None:
    """Add standard --debug/-d argument to parser.

    Args:
        parser: ArgumentParser instance to modify
        default: Default debug value (typically from config)
    """
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        default=default,
        help="Enable debug logging",
    )


def add_apply_argument(
    parser: argparse.ArgumentParser,
    default: bool = False,
    help_text: str = "Apply changes to remote host via SSH",
) -> None:
    """Add standard --apply argument to parser.

    Args:
        parser: ArgumentParser instance to modify
        default: Default apply value (typically from config)
        help_text: Help text for the --apply argument
    """
    parser.add_argument(
        "--apply",
        action="store_true",
        default=default,
        help=help_text,
    )


def add_sheet_arguments(
    parser: argparse.ArgumentParser,
    globals_cfg: dict[str, Any],
    nodes_gid: int | None = None,
    services_gid: int | None = None,
    dns_gid: int | None = None,
) -> None:
    """Add standard Google Sheets-related arguments to parser.

    Args:
        parser: ArgumentParser instance to modify
        globals_cfg: [globals] config table for defaults
        nodes_gid: Default nodes GID (if applicable)
        services_gid: Default services GID (if applicable)
        dns_gid: Legacy default DNS GID (if applicable)
    """
    from .config import DEFAULT_SHEET_URL

    parser.add_argument(
        "--sheet-url",
        default=get_config_value(globals_cfg, "sheet_url", DEFAULT_SHEET_URL),
        help="Google Sheets CSV export URL containing 'gid=0' that will be replaced with tab-specific GIDs",
    )

    if nodes_gid is not None:
        parser.add_argument(
            "--nodes-gid",
            type=int,
            default=int(get_config_value(globals_cfg, "nodes_gid", nodes_gid)),
            help="GID for Nodes sheet",
        )

    if services_gid is not None:
        default_services = int(
            get_config_value(
                globals_cfg,
                "services_gid",
                get_config_value(globals_cfg, "dns_gid", services_gid),
            )
        )
        parser.add_argument(
            "--services-gid",
            type=int,
            default=default_services,
            help="GID for Services sheet",
        )

        # Backward-compatible alias for older configs/flags
        if dns_gid is not None:
            parser.add_argument(
                "--dns-gid",
                dest="services_gid",
                type=int,
                default=argparse.SUPPRESS,
                help=argparse.SUPPRESS,
            )


def bootstrap_config_and_logging(
    argv: list[str] | None = None,
    tool_name: str | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Bootstrap config and logging for a CLI tool.

    This is the standard entrypoint for CLI tools: it parses --config and --debug early,
    loads the TOML config, configures logging, and returns config tables.

    Args:
        argv: Command-line arguments (None = sys.argv[1:])
        tool_name: Name of the tool section in TOML (e.g., "pihole", "dnscontrol")

    Returns:
        Tuple of (config_path, config_dict, globals_cfg, tool_cfg)
        where:
          - config_path: Resolved Path to the TOML config file
          - config_dict: Full parsed TOML config
          - globals_cfg: [globals] section (or empty dict)
          - tool_cfg: [tool_name] section (or empty dict) if tool_name provided
    """
    config_path, config = pre_parse_config(argv)

    # Pre-parse debug flag to configure logging before building parser
    debug = False
    if argv:
        debug = "--debug" in argv or "-d" in argv

    configure_logging(debug=debug)

    if tool_name:
        logger.debug("%s: config_path=%s", tool_name, config_path)

    globals_cfg = get_table(config, "globals")
    tool_cfg = get_table(config, tool_name) if tool_name else {}

    return config_path, config, globals_cfg, tool_cfg


def build_base_parser(
    description: str,
    config_path: Path,
    globals_cfg: dict[str, Any],
    tool_cfg: dict[str, Any] | None = None,
    add_debug: bool = True,
) -> argparse.ArgumentParser:
    """Build a parser with standard --config and --debug arguments pre-populated.

    Args:
        description: Parser description text
        config_path: Default config path (from bootstrap_config_and_logging)
        globals_cfg: [globals] config table
        tool_cfg: Tool-specific config table (for debug default)
        add_debug: Whether to add --debug argument (default: True)

    Returns:
        ArgumentParser with --config and optionally --debug already added
    """
    parser = argparse.ArgumentParser(description=description)
    add_config_argument(parser, config_path)

    if add_debug:
        default_debug = False
        if tool_cfg:
            default_debug = bool(get_config_value(tool_cfg, "debug", False))
        if not default_debug:
            default_debug = bool(get_config_value(globals_cfg, "debug", False))
        add_debug_argument(parser, default=default_debug)

    return parser


def validate_required(
    value: Any,
    name: str,
    error_message: str | None = None,
) -> None:
    """Validate that a required value is present and non-empty.

    Args:
        value: Value to validate
        name: Name of the value (for error message)
        error_message: Custom error message (default: auto-generated)

    Raises:
        SystemExit(2) if validation fails
    """
    if not value:
        if error_message is None:
            error_message = f"Error: {name} is required"
        print(error_message, file=sys.stderr)
        sys.exit(2)


def resolve_and_validate_paths(
    config_path: Path,
    *paths: tuple[str, Path | str],
) -> dict[str, Path]:
    """Resolve multiple paths relative to config and validate they're not templates.

    Args:
        config_path: Base config file path
        *paths: Variable number of (name, path) tuples

    Returns:
        Dict mapping names to resolved Paths

    Example:
        resolved = resolve_and_validate_paths(
            config_path,
            ("template", args.template),
            ("output", args.output),
        )
        template_path = resolved["template"]
        output_path = resolved["output"]
    """
    from .config import resolve_path_relative_to_config

    resolved = {}
    for name, path in paths:
        resolved_path = resolve_path_relative_to_config(config_path, Path(path))
        resolved[name] = resolved_path

        # Warn if output looks like a template
        if name == "output" and resolved_path.suffix in {".j2", ".jinja", ".jinja2"}:
            print(
                f"Warning: output path looks like a template: {resolved_path}",
                file=sys.stderr,
            )

    return resolved
