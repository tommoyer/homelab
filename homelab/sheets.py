from __future__ import annotations

import hashlib
import ipaddress
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

import pandas as pd

_SHEET_DF_CACHE: dict[tuple[str, int], pd.DataFrame] = {}
_SHEET_DF_CACHE_LOCK = threading.Lock()

_KEEP_DOWNLOADED_CSV = False
_KEEP_DOWNLOADED_CSV_DIR = Path(tempfile.gettempdir()) / "homelab-sheets"


def configure_sheet_csv_retention(*, keep: bool, output_dir: str | Path | None = None) -> None:
    global _KEEP_DOWNLOADED_CSV
    global _KEEP_DOWNLOADED_CSV_DIR

    _KEEP_DOWNLOADED_CSV = bool(keep)
    if output_dir is not None:
        _KEEP_DOWNLOADED_CSV_DIR = Path(output_dir)


def _maybe_write_downloaded_csv(*, csv_text: str, label: str, gid: int, url: str) -> None:
    if not _KEEP_DOWNLOADED_CSV:
        return

    _KEEP_DOWNLOADED_CSV_DIR.mkdir(parents=True, exist_ok=True)
    safe_label = normalize_column_name(label) or "sheet"
    url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    output_path = _KEEP_DOWNLOADED_CSV_DIR / f"{safe_label}-gid{int(gid)}-{url_hash}.csv"
    output_path.write_text(csv_text, encoding="utf-8")
    print(f"Saved {label} CSV to {output_path}", flush=True)


def get_sheet_df(sheet_url: str, gid: int, timeout_seconds: float, label: str) -> pd.DataFrame:
    """Load a Google Sheet tab as a DataFrame, caching by (sheet_url, gid)."""
    key = (sheet_url, int(gid))
    with _SHEET_DF_CACHE_LOCK:
        if key in _SHEET_DF_CACHE:
            return _SHEET_DF_CACHE[key]
    # Only import requests/io here to avoid circular import
    import io

    import requests
    url = build_sheet_url(sheet_url, int(gid))
    print(f"Loading {label} sheet data...", flush=True)
    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    csv_text = response.text
    _maybe_write_downloaded_csv(csv_text=csv_text, label=label, gid=int(gid), url=url)
    df = df_with_normalized_columns(pd.read_csv(io.StringIO(csv_text)))
    with _SHEET_DF_CACHE_LOCK:
        _SHEET_DF_CACHE[key] = df
    return df


def clear_sheet_df_cache():
    with _SHEET_DF_CACHE_LOCK:
        _SHEET_DF_CACHE.clear()


def build_sheet_url(sheet_url: str, gid: int) -> str:
    if "gid=0" not in sheet_url:
        raise ValueError("sheet_url must contain 'gid=0' placeholder")
    return sheet_url.replace("gid=0", f"gid={gid}")


def normalize_column_name(name: str) -> str:
    name = (name or "").strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


def df_with_normalized_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [normalize_column_name(str(col)) for col in df.columns]
    return df


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def as_str(value: Any) -> str:
    if is_blank(value):
        return ""
    return str(value).strip()


def normalize_int_cell(value: object) -> str:
    """Normalize values that should be integers but may arrive as floats/strings.

    Examples:
      - 20.0 -> "20"
      - "20.0" -> "20"
      - " 20 " -> "20"
    """

    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip()

    cleaned = str(value).strip()
    if not cleaned:
        return ""
    m = re.match(r"^(\d+)\.0+$", cleaned)
    if m:
        return m.group(1)
    return cleaned


def parse_bool(value: Any, default: bool = False) -> bool:
    if is_blank(value):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in {"true", "t", "yes", "y", "1", "on"}:
            return True
        if cleaned in {"false", "f", "no", "n", "0", "off"}:
            return False
    return default


def normalize_ports(value: Any) -> list[int]:
    if is_blank(value) or value is None:
        return []
    if isinstance(value, list):
        ports: list[int] = []
        for item in value:
            ports.extend(normalize_ports(item))
        return ports
    if isinstance(value, (int, float)):
        try:
            return [int(value)]
        except (TypeError, ValueError):
            return []
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return []
        parts = re.split(r"[\s,;/]+", cleaned)
        ports: list[int] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part.isdigit():
                ports.append(int(part))
        return ports
    return []


def normalize_ip(address: str) -> str | None:
    tokens = (address or "").strip().split()
    if not tokens:
        return None
    address = tokens[0]
    try:
        return str(ipaddress.ip_interface(address).ip)
    except ValueError:
        try:
            return str(ipaddress.ip_address(address))
        except ValueError:
            return None


def load_nodes_lookup(nodes_df: pd.DataFrame) -> dict[str, str]:
    """Build a hostname/dns_name -> IP lookup from a Nodes DataFrame.

    Columns are normalized internally; callers need not pre-normalize.
    """

    df = df_with_normalized_columns(nodes_df)
    lookup: dict[str, str] = {}
    for _, row in df.iterrows():
        dns_name = as_str(row.get("dns_name"))
        hostname = as_str(row.get("hostname"))
        ip = normalize_ip(as_str(row.get("ip_address")))
        if not ip:
            continue
        if dns_name:
            lookup[dns_name.lower()] = ip
        if hostname:
            lookup[hostname.lower()] = ip
    return lookup
