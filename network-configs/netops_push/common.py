from __future__ import annotations

import difflib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import yaml


@dataclass(frozen=True)
class SSHSpec:
    host: str
    user: str
    port: int = 22
    use_sudo: bool = False
    identity_file: Optional[str] = None


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def run_cmd(
    cmd: list[str],
    *,
    cwd: Optional[Path] = None,
    input_text: Optional[str] = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    kwargs = {
        "cwd": str(cwd) if cwd else None,
        "text": True,
        "input": input_text,
    }
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    p = subprocess.run(cmd, **{k: v for k, v in kwargs.items() if v is not None})
    if check and p.returncode != 0:
        stderr = getattr(p, "stderr", None)
        stdout = getattr(p, "stdout", None)
        msg = f"Command failed ({p.returncode}): {' '.join(cmd)}"
        if stdout:
            msg += f"\n--- stdout ---\n{stdout}"
        if stderr:
            msg += f"\n--- stderr ---\n{stderr}"
        raise RuntimeError(msg)
    return p


def _ssh_base_args(spec: SSHSpec) -> list[str]:
    args = [
        "ssh",
        "-p",
        str(spec.port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if spec.identity_file:
        args += ["-i", spec.identity_file]
    return args


def _scp_base_args(spec: SSHSpec) -> list[str]:
    args = [
        "scp",
        "-P",
        str(spec.port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if spec.identity_file:
        args += ["-i", spec.identity_file]
    return args


def ssh_run(spec: SSHSpec, remote_cmd: str, *, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = _ssh_base_args(spec) + [f"{spec.user}@{spec.host}", remote_cmd]
    return run_cmd(cmd, capture=capture, check=True)


def ssh_run_lines(spec: SSHSpec, lines: Iterable[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    # Feeds commands via stdin (useful for RouterOS CLI).
    cmd = _ssh_base_args(spec) + ["-T", f"{spec.user}@{spec.host}"]
    payload = "\n".join(lines) + "\n"
    return run_cmd(cmd, input_text=payload, capture=capture, check=True)


def scp_download(spec: SSHSpec, remote_path: str, local_path: Path) -> None:
    ensure_dir(local_path.parent)
    cmd = _scp_base_args(spec) + [f"{spec.user}@{spec.host}:{remote_path}", str(local_path)]
    run_cmd(cmd, check=True)


def scp_upload(spec: SSHSpec, local_path: Path, remote_path: str) -> None:
    cmd = _scp_base_args(spec) + [str(local_path), f"{spec.user}@{spec.host}:{remote_path}"]
    run_cmd(cmd, check=True)


def unified_diff_text(a: str, b: str, fromfile: str, tofile: str) -> str:
    diff = difflib.unified_diff(
        a.splitlines(keepends=True),
        b.splitlines(keepends=True),
        fromfile=fromfile,
        tofile=tofile,
    )
    return "".join(diff)


def load_yaml_documents(path: Path) -> list[dict]:
    """
    Loads one or more YAML documents from:
      - a single YAML file, or
      - a directory of YAML files (recursively).
    Assumes each file is a single YAML document.
    """
    if path.is_file():
        with path.open("r", encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        if not isinstance(doc, dict):
            raise ValueError(f"Expected mapping at top-level in {path}")
        return [doc]

    if path.is_dir():
        docs: list[dict] = []
        for fp in sorted(list(path.rglob("*.yml")) + list(path.rglob("*.yaml"))):
            with fp.open("r", encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
            if not isinstance(doc, dict):
                raise ValueError(f"Expected mapping at top-level in {fp}")
            docs.append(doc)
        return docs

    raise FileNotFoundError(str(path))


def rm_tree_if_exists(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)

