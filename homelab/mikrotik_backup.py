from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import (
    get_table,
    load_toml_or_exit,
    merge_config_tables,
    resolve_path_relative_to_config,
)
from .mikrotik_utils import (
    download_remote_file_via_scp,
    export_router_config_via_ssh_to_file,
    remove_remote_file,
    sanitize_filename_component,
)
from .ssh import (
    prefix_sshpass,
    require_command,
    scp_base_args,
    ssh_base_args,
    ssh_control_path,
    ssh_start_master,
    ssh_stop_master,
    sshpass_env_from_password_env,
)

_DEFAULT_KEEP = 3

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Device:
    name: str
    host: str
    user: str
    ssh_port: int
    ssh_identity_file: Path | None
    backup_dir: Path
    password_env: str | None


def _device_from_config(
    *,
    config_path: Path,
    name: str,
    device_cfg: dict,
    defaults: dict,
    default_backup_dir: Path,
) -> Device:
    host = str(device_cfg.get("host", "")).strip()
    user = str(device_cfg.get("user", defaults.get("mikrotik_user", defaults.get("user", "")))).strip()
    if not host or not user:
        raise ValueError(f"Device '{name}' must define host (and user or defaults.user)")

    ssh_port = int(device_cfg.get("ssh_port", defaults.get("ssh_port", 22)))

    identity_raw = device_cfg.get("ssh_identity_file", defaults.get("ssh_identity_file", ""))
    identity_str = str(identity_raw or "").strip()
    identity_file = resolve_path_relative_to_config(config_path, identity_str) if identity_str else None

    backup_dir_raw = device_cfg.get("backup_dir", defaults.get("backup_dir", str(default_backup_dir)))
    backup_dir = resolve_path_relative_to_config(config_path, str(backup_dir_raw))

    password_env_raw = device_cfg.get("password_env", defaults.get("password_env", ""))
    password_env = str(password_env_raw or "").strip() or None

    return Device(
        name=name,
        host=host,
        user=user,
        ssh_port=ssh_port,
        ssh_identity_file=identity_file,
        backup_dir=backup_dir,
        password_env=password_env,
    )


def build_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    default_config = Path.cwd().resolve() / "config.toml"
    parser = argparse.ArgumentParser(
        description=(
            "Back up MikroTik RouterOS configuration by running /export over SSH, "
            "downloading the resulting .rsc via scp, and removing the remote file."
        )
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=default_config,
        help="Path to TOML config file containing device inventory and defaults",
    )

    parser.add_argument("--device", help="Device name from [devices.<name>] to back up")
    parser.add_argument("--all", action="store_true", help="Back up all devices in the config")

    parser.add_argument("--mikrotik-host", help="Hostname/IP (direct mode)")
    parser.add_argument("--mikrotik-user", help="SSH username (direct mode)")
    parser.add_argument(
        "--password-env",
        default=None,
        help=(
            "Environment variable containing the SSH password (used via sshpass). "
            "If set, sshpass is required. Example: MIKROTIK_PASSWORD"
        ),
    )
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH port (direct mode; default: 22)")
    parser.add_argument("--ssh-identity-file", type=Path, help="SSH key path (direct mode)")

    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Override backup directory (direct mode or single-device mode)",
    )

    parser.add_argument(
        "--cleanup",
        action="store_true",
        default=None,
        help=(
            "Delete old backups for each device before downloading the new one, "
            "keeping the most recent N files (see --keep). "
            "Can also be set via mikrotik_backup.defaults.cleanup in config.toml."
        ),
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Disable cleanup even if enabled in config.toml.",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=None,
        metavar="N",
        help=(
            f"Number of existing backups to retain per device when --cleanup is used "
            f"(default: {_DEFAULT_KEEP}). The new backup is NOT counted. "
            f"Can also be set via mikrotik_backup.defaults.keep in config.toml."
        ),
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Perform the backup (runs /export over SSH, downloads via scp, then removes the remote file). "
            "Without --apply, prints what would be done without touching the router."
        ),
    )

    return parser


def _find_old_backups(*, device: Device) -> list[Path]:
    """Return existing backup files for *device*, oldest first."""
    safe_name = sanitize_filename_component(device.name)
    safe_host = sanitize_filename_component(device.host)
    pattern = f"router-export-{safe_name}-{safe_host}-*.rsc"
    matches = sorted(device.backup_dir.glob(pattern))
    return matches


def cleanup_old_backups(*, device: Device, keep: int, dry_run: bool = False) -> list[Path]:
    """Delete old backups for *device*, keeping the *keep* most recent files.

    Returns the list of paths that were (or would be, when *dry_run*) removed.
    """
    existing = _find_old_backups(device=device)
    if len(existing) <= keep:
        return []

    to_remove = existing[: len(existing) - keep]

    if not dry_run:
        for p in to_remove:
            logger.info("Deleting old backup: %s", p)
            p.unlink()

    return to_remove


def backup_device(*, device: Device) -> Path:
    require_command("ssh")
    require_command("scp")

    run_env = sshpass_env_from_password_env(password_env=device.password_env)
    use_sshpass = run_env is not None
    if use_sshpass:
        require_command("sshpass")

    if device.ssh_identity_file is not None and not device.ssh_identity_file.exists():
        raise RuntimeError(f"SSH identity file not found: {device.ssh_identity_file}")

    target = f"{device.user}@{device.host}"
    logger.debug("mikrotik-backup: target=%s port=%s", target, device.ssh_port)
    control_path = ssh_control_path(prefix="mikrotik", username=device.user, host=device.host, port=device.ssh_port)

    ssh_args = prefix_sshpass(
        ssh_base_args(control_path=control_path, port=device.ssh_port, identity_file=device.ssh_identity_file),
        enabled=use_sshpass,
    )
    scp_args = prefix_sshpass(
        scp_base_args(control_path=control_path, port=device.ssh_port, identity_file=device.ssh_identity_file),
        enabled=use_sshpass,
    )

    timestamp = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_name = sanitize_filename_component(device.name)
    safe_host = sanitize_filename_component(device.host)
    export_base = f"router-export-{safe_name}-{safe_host}-{timestamp}"

    local_path = device.backup_dir / f"{export_base}.rsc"
    logger.debug("mikrotik-backup: local_path=%s", local_path)

    try:
        ssh_start_master(ssh_args=ssh_args, target=target, env=run_env)

        remote_filename = export_router_config_via_ssh_to_file(
            ssh_args=ssh_args,
            target=target,
            export_base_name=export_base,
            env=run_env,
        )

        download_remote_file_via_scp(
            scp_args=scp_args,
            target=target,
            remote_filename=remote_filename,
            local_path=local_path,
            attempts=6,
            delay_seconds=0.5,
            env=run_env,
        )

        remove_remote_file(ssh_args=ssh_args, target=target, remote_filename=remote_filename, env=run_env)
    finally:
        ssh_stop_master(ssh_args=ssh_args, target=target, env=run_env)

    return local_path


def plan_backup(*, device: Device) -> tuple[str, Path]:
    """Return (remote_export_base, local_path) for a backup without executing it."""

    timestamp = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_name = sanitize_filename_component(device.name)
    safe_host = sanitize_filename_component(device.host)
    export_base = f"router-export-{safe_name}-{safe_host}-{timestamp}"
    local_path = device.backup_dir / f"{export_base}.rsc"
    return export_base, local_path


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(argv)
    args = parser.parse_args(argv)

    logger.debug("mikrotik-backup: argv=%r", argv)

    config_path = args.config.expanduser().resolve()
    logger.debug("mikrotik-backup: config_path=%s", config_path)
    cfg = load_toml_or_exit(config_path)

    globals_cfg = get_table(cfg, "globals")
    mk_defaults = get_table(cfg, "mikrotik_defaults")

    # New unified config prefers a dedicated section.
    mk_backup = cfg.get("mikrotik_backup") if isinstance(cfg.get("mikrotik_backup", None), dict) else None
    if mk_backup is not None:
        mk_backup_defaults = mk_backup.get("defaults", {}) if isinstance(mk_backup.get("defaults", {}), dict) else {}
        defaults = merge_config_tables(globals_cfg, mk_defaults, mk_backup_defaults)
        devices_cfg = mk_backup.get("devices", {}) if isinstance(mk_backup.get("devices", {}), dict) else {}
    else:
        legacy_defaults = cfg.get("defaults", {}) if isinstance(cfg.get("defaults", {}), dict) else {}
        defaults = merge_config_tables(globals_cfg, mk_defaults, legacy_defaults)
        devices_cfg = cfg.get("devices", {}) if isinstance(cfg.get("devices", {}), dict) else {}

    tool_backup_dir = Path(__file__).resolve().parent / "mikrotik" / "backups"
    default_backup_dir = resolve_path_relative_to_config(
        config_path,
        str(defaults.get("backup_dir", str(tool_backup_dir))),
    )

    devices: list[Device] = []

    if args.all:
        if not devices_cfg:
            print(f"Error: no devices found in config: {config_path}", file=sys.stderr)
            return 2
        for name, dev_cfg in devices_cfg.items():
            if not isinstance(dev_cfg, dict):
                continue
            devices.append(
                _device_from_config(
                    config_path=config_path,
                    name=str(name),
                    device_cfg=dev_cfg,
                    defaults=defaults,
                    default_backup_dir=default_backup_dir,
                )
            )

    elif args.device:
        dev_cfg = devices_cfg.get(args.device)
        if not isinstance(dev_cfg, dict):
            print(f"Error: device not found in config: {args.device}", file=sys.stderr)
            return 2
        devices.append(
            _device_from_config(
                config_path=config_path,
                name=str(args.device),
                device_cfg=dev_cfg,
                defaults=defaults,
                default_backup_dir=default_backup_dir,
            )
        )

    elif args.mikrotik_host and args.mikrotik_user:
        backup_dir = (
            resolve_path_relative_to_config(config_path, args.backup_dir)
            if args.backup_dir is not None
            else default_backup_dir
        )
        identity_file = (
            resolve_path_relative_to_config(config_path, args.ssh_identity_file)
            if args.ssh_identity_file is not None
            else None
        )
        devices.append(
            Device(
                name=sanitize_filename_component(args.mikrotik_host),
                host=str(args.mikrotik_host),
                user=str(args.mikrotik_user),
                ssh_port=int(args.ssh_port),
                ssh_identity_file=identity_file,
                backup_dir=backup_dir,
                password_env=str(args.password_env).strip() or None,
            )
        )

    else:
        print(
            "Error: provide either --device, --all, or --mikrotik-host/--mikrotik-user (direct mode)",
            file=sys.stderr,
        )
        print(f"Config file used: {config_path}", file=sys.stderr)
        return 2

    if args.backup_dir is not None:
        if len(devices) != 1:
            print("Error: --backup-dir is only supported for single-device runs", file=sys.stderr)
            return 2
        devices[0] = Device(
            name=devices[0].name,
            host=devices[0].host,
            user=devices[0].user,
            ssh_port=devices[0].ssh_port,
            ssh_identity_file=devices[0].ssh_identity_file,
            backup_dir=resolve_path_relative_to_config(config_path, args.backup_dir),
            password_env=devices[0].password_env,
        )

    if args.password_env is not None:
        if len(devices) != 1:
            print("Error: --password-env is only supported for single-device runs", file=sys.stderr)
            return 2
        devices[0] = Device(
            name=devices[0].name,
            host=devices[0].host,
            user=devices[0].user,
            ssh_port=devices[0].ssh_port,
            ssh_identity_file=devices[0].ssh_identity_file,
            backup_dir=devices[0].backup_dir,
            password_env=str(args.password_env).strip() or None,
        )

    # Resolve cleanup/keep: CLI flags > config.toml > built-in defaults.
    cfg_cleanup = bool(defaults.get("cleanup", False))
    cfg_keep = defaults.get("keep", _DEFAULT_KEEP)

    if args.no_cleanup:
        do_cleanup = False
    elif args.cleanup is not None:
        do_cleanup = True
    else:
        do_cleanup = cfg_cleanup

    keep = int(args.keep if args.keep is not None else cfg_keep)
    if keep < 0:
        print("Error: --keep must be >= 0", file=sys.stderr)
        return 2

    if not bool(args.apply):
        print("Dry run (no --apply): no remote changes made")
        for device in devices:
            export_base, local_path = plan_backup(device=device)
            target = f"{device.user}@{device.host}"
            print(f"- device: {device.name} ({target}, port {device.ssh_port})")
            if do_cleanup:
                stale = cleanup_old_backups(device=device, keep=keep, dry_run=True)
                if stale:
                    print(f"  - would delete {len(stale)} old backup(s) (keeping {keep}):")
                    for p in stale:
                        print(f"    - {p}")
                else:
                    print(f"  - nothing to clean up ({len(_find_old_backups(device=device))} <= {keep})")
            print(f"  - would ssh: {target} run /export (producing {export_base}.rsc)")
            print(f"  - would scp: {target}:{export_base}.rsc -> {local_path}")
            print(f"  - would ssh: {target} remove {export_base}.rsc")
        print("Re-run with --apply to perform these actions.")
        return 0

    for device in devices:
        if do_cleanup:
            removed = cleanup_old_backups(device=device, keep=keep)
            for p in removed:
                print(f"Deleted old backup for {device.name}: {p}")
        try:
            path = backup_device(device=device)
        except Exception as exc:
            print(f"Error: backup failed for device '{device.name}': {exc}", file=sys.stderr)
            return 1
        print(f"Wrote export backup for {device.name}: {path}")

    return 0
