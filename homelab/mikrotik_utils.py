from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .ssh import ssh_run


def sanitize_filename_component(value: str) -> str:
    """Sanitize a string for safe use as a filename component."""

    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in value)


def mikrotik_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def export_router_config_via_ssh_to_file(
    *,
    ssh_args: list[str],
    target: str,
    export_base_name: str,
    env: dict[str, str] | None,
) -> str:
    remote_file = f"{export_base_name}.rsc"

    export_cmds = [
        f"/export file={export_base_name} hide-sensitive=yes",
        f"/export file={export_base_name} show-sensitive=no",
        f"/export file={export_base_name}",
    ]

    last_error: str | None = None
    for cmd in export_cmds:
        try:
            ssh_run(ssh_args=ssh_args, target=target, command=cmd, check=True, env=env)
            return remote_file
        except subprocess.CalledProcessError as exc:
            last_error = (exc.stderr or exc.stdout or str(exc)).strip()
            continue

    raise RuntimeError(f"Failed to export router configuration via SSH: {last_error}")


def download_remote_file_via_scp(
    *,
    scp_args: list[str],
    target: str,
    remote_filename: str,
    local_path: Path,
    env: dict[str, str] | None,
    attempts: int = 1,
    delay_seconds: float = 0.5,
) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)

    last_error: str | None = None
    for attempt in range(max(attempts, 1)):
        try:
            subprocess.run(
                [*scp_args, f"{target}:{remote_filename}", str(local_path)],
                check=True,
                env=env,
            )
            return
        except subprocess.CalledProcessError as exc:
            last_error = str(exc)
            if attempt + 1 < attempts:
                time.sleep(delay_seconds)

    raise RuntimeError(f"Failed to download export via scp after {attempts} attempts: {last_error}")


def remove_remote_file(
    *,
    ssh_args: list[str],
    target: str,
    remote_filename: str,
    env: dict[str, str] | None,
) -> None:
    ssh_run(
        ssh_args=ssh_args,
        target=target,
        command=f"/file remove {remote_filename}",
        check=False,
        env=env,
    )
