from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"required command not found in PATH: {name}")


def ssh_control_path(*, prefix: str, username: str, host: str, port: int | None = None) -> Path:
    key = f"{username}@{host}:{port or ''}".encode("utf-8")
    digest = hashlib.sha1(key).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"{prefix}-ssh-{digest}.sock"


def ssh_mux_options(control_path: Path) -> list[str]:
    return [
        "-o",
        "ControlMaster=auto",
        "-o",
        "ControlPersist=60s",
        "-o",
        f"ControlPath={control_path}",
    ]


def prefix_sshpass(argv: Iterable[str], *, enabled: bool) -> list[str]:
    argv_list = list(argv)
    return (["sshpass", "-e", *argv_list] if enabled else argv_list)


def sshpass_env_from_password_env(*, password_env: str | None) -> dict[str, str] | None:
    if not password_env:
        return None
    env_value = os.environ.get(password_env)
    if not env_value:
        raise RuntimeError(f"password environment variable is not set: {password_env}")
    env = dict(os.environ)
    env["SSHPASS"] = env_value
    return env


def ssh_base_args(*, control_path: Path, port: int, identity_file: Path | None) -> list[str]:
    args: list[str] = ["ssh", *(ssh_mux_options(control_path)), "-p", str(port)]
    if identity_file is not None:
        args.extend(["-i", str(identity_file)])
    return args


def scp_base_args(*, control_path: Path, port: int, identity_file: Path | None) -> list[str]:
    args: list[str] = ["scp", *(ssh_mux_options(control_path)), "-P", str(port)]
    if identity_file is not None:
        args.extend(["-i", str(identity_file)])
    return args


def ssh_start_master(*, ssh_args: list[str], target: str, env: dict[str, str] | None) -> None:
    subprocess.run([*ssh_args, "-Nf", target], check=True, env=env)


def ssh_stop_master(*, ssh_args: list[str], target: str, env: dict[str, str] | None) -> None:
    subprocess.run([*ssh_args, "-O", "exit", target], check=False, env=env)


def ssh_run(
    *,
    ssh_args: list[str],
    target: str,
    command: str,
    check: bool = True,
    env: dict[str, str] | None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*ssh_args, target, command],
        check=check,
        text=True,
        capture_output=True,
        env=env,
    )
