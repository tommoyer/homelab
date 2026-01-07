#!/usr/bin/env python3
"""
netops_lib.py

Shared helpers for YAML SoT-based generators/appliers.

Dependencies:
  - Python 3.11+ (tomllib)
  - pip install pyyaml  (required)

Optional system tools:
  - ssh / scp (for Pi-hole + Mikrotik apply)
  - sshpass (optional; reduces Mikrotik password prompts)
  - dnscontrol (for Cloudflare apply)

This module is extracted/refactored from update-network-configs.py
and adapted to read data/*.yaml instead of a CSV.
"""

from __future__ import annotations

import datetime
import getpass
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import tomllib
except ImportError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except Exception:
        tomllib = None  # type: ignore

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # type: ignore


# ----------------------------- config + YAML ---------------------------------

def load_config_toml(config_path: str) -> Tuple[Dict[str, Any], Optional[str]]:
    """Load TOML config. Try provided path, then relative to this file."""
    if tomllib is None:
        raise RuntimeError("Missing TOML parser: use Python 3.11+ or `pip install tomli`")

    if os.path.isfile(config_path):
        with open(config_path, "rb") as f:
            return tomllib.load(f), config_path

    script_dir = os.path.dirname(os.path.abspath(__file__))
    alt_path = os.path.join(script_dir, config_path)
    if os.path.isfile(alt_path):
        print(f"[Info] Config not found at '{config_path}', using '{alt_path}'")
        with open(alt_path, "rb") as f:
            return tomllib.load(f), alt_path

    print(f"[Warning] Config file not found: {config_path}", file=sys.stderr)
    return {}, None


def load_yaml_file(path: str) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("Missing dependency: PyYAML. Install with: pip install pyyaml")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"YAML root must be a mapping in {path}")
        return data


def load_sot(data_dir: str) -> Dict[str, Any]:
    """
    Loads:
      - assets.yaml
      - services.yaml
      - dns_names.yaml
      - vlans.yaml (optional)
    Returns a dict with keys: assets, services, dns_names, vlans_doc (optional).
    """
    assets_doc = load_yaml_file(os.path.join(data_dir, "assets.yaml"))
    services_doc = load_yaml_file(os.path.join(data_dir, "services.yaml"))
    dns_doc = load_yaml_file(os.path.join(data_dir, "dns_names.yaml"))

    vlans_path = os.path.join(data_dir, "vlans.yaml")
    vlans_doc = None
    if os.path.isfile(vlans_path):
        vlans_doc = load_yaml_file(vlans_path)

    assets = assets_doc.get("assets", [])
    services = services_doc.get("services", [])
    dns_names = dns_doc.get("dns_names", [])

    if not isinstance(assets, list) or not isinstance(services, list) or not isinstance(dns_names, list):
        raise ValueError("Invalid SoT YAML structure (assets/services/dns_names must be lists).")

    assets_by_id = {a.get("asset_id"): a for a in assets if isinstance(a, dict) and a.get("asset_id")}
    services_by_id = {s.get("service_id"): s for s in services if isinstance(s, dict) and s.get("service_id")}

    return {
        "assets": assets,
        "services": services,
        "dns_names": dns_names,
        "assets_by_id": assets_by_id,
        "services_by_id": services_by_id,
        "vlans_doc": vlans_doc,
    }


# ----------------------------- prerequisites ---------------------------------

def check_prerequisites(*, needs_dnscontrol: bool = False) -> bool:
    missing = []
    if not shutil.which("ssh"):
        missing.append("ssh")
    if not shutil.which("scp"):
        missing.append("scp")
    if needs_dnscontrol and not shutil.which("dnscontrol"):
        missing.append("dnscontrol")

    if not missing:
        return True

    print("\n[!] CRITICAL ERROR: Missing required system tools.", file=sys.stderr)
    print(f"    Missing: {', '.join(missing)}", file=sys.stderr)

    system = platform.system().lower()
    if "dnscontrol" in missing:
        print("\n--- How to install DNSControl ---")
        if system == "darwin":
            print("    brew install dnscontrol")
        elif system == "linux":
            print("    Visit DNSControl releases/docs for your distro packaging.")
        else:
            print("    Visit: https://docs.dnscontrol.org/getting-started/installation")

    if "ssh" in missing or "scp" in missing:
        print("\n--- How to install SSH/SCP ---")
        if system == "windows":
            print("    Enable OpenSSH Client in Windows Features or install Git for Windows.")
        else:
            print("    sudo apt install openssh-client  # Ubuntu/Debian")

    if not shutil.which("sshpass"):
        print("\n[Info] 'sshpass' not found (optional). Install to avoid repeated Mikrotik password prompts.", file=sys.stderr)

    return False


# ----------------------------- SSH helpers -----------------------------------

def run_cmd(cmd: str, *, explanation: Optional[str] = None, dry_run: bool = False) -> Tuple[int, str, str]:
    if explanation:
        print(f"=> {explanation}")
    if dry_run:
        print(f"[Dry Run] CMD: {cmd}")
        return 0, "", ""
    p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", errors="ignore"), p.stderr.decode("utf-8", errors="ignore")


def _sshpass_prefix(password: Optional[str]) -> str:
    if password and shutil.which("sshpass"):
        return f"sshpass -p {shlex.quote(password)} "
    return ""


def scp_to_remote(
    local_path: str,
    remote_user_host: str,
    remote_tmp_path: str,
    *,
    ssh_port: Optional[str] = None,
    password: Optional[str] = None,
    dry_run: bool = False,
) -> Tuple[int, str, str]:
    port_flag = f"-P {ssh_port}" if ssh_port else ""
    prefix = _sshpass_prefix(password)
    cmd = f"{prefix}scp -o LogLevel=ERROR {port_flag} {shlex.quote(local_path)} {shlex.quote(remote_user_host)}:{shlex.quote(remote_tmp_path)}"
    return run_cmd(cmd, explanation=f"Copying file to {remote_user_host}:{remote_tmp_path}", dry_run=dry_run)


def scp_from_remote(
    remote_user_host: str,
    remote_path: str,
    local_path: str,
    *,
    ssh_port: Optional[str] = None,
    password: Optional[str] = None,
    dry_run: bool = False,
) -> Tuple[int, str, str]:
    port_flag = f"-P {ssh_port}" if ssh_port else ""
    prefix = _sshpass_prefix(password)
    cmd = f"{prefix}scp -o LogLevel=ERROR {port_flag} {shlex.quote(remote_user_host)}:{shlex.quote(remote_path)} {shlex.quote(local_path)}"
    return run_cmd(cmd, explanation=f"Copying file from {remote_user_host}:{remote_path}", dry_run=dry_run)


def ssh_run(
    remote_user_host: str,
    remote_cmd: str,
    *,
    ssh_port: Optional[str] = None,
    password: Optional[str] = None,
    dry_run: bool = False,
) -> Tuple[int, str, str]:
    port_flag = f"-p {ssh_port}" if ssh_port else ""
    prefix = _sshpass_prefix(password)
    opts = "-o LogLevel=ERROR"
    cmd = f"{prefix}ssh {port_flag} {opts} {shlex.quote(remote_user_host)} {shlex.quote(remote_cmd)}"
    return run_cmd(cmd, explanation=f"Running remote command on {remote_user_host}", dry_run=dry_run)


def prompt_password_once(existing: Optional[str], *, who: str, dry_run: bool) -> Optional[str]:
    if existing or dry_run:
        return existing
    if shutil.which("sshpass"):
        print(f"\n[Input] Enter SSH password for {who}:")
        return getpass.getpass()
    # If sshpass is missing, let ssh prompt interactively.
    return None


# ----------------------------- Pi-hole TOML ----------------------------------

def build_hosts_block(entries: List[Dict[str, Any]], *, indent: str = "") -> str:
    unique = {e["fqdn"]: e["ip"] for e in entries}
    lines = [f"{indent}hosts = ["]
    for fqdn, ip in unique.items():
        val = f"{ip} {fqdn}"
        lines.append(f'{indent}  "{val}",')
    if len(lines) > 1:
        lines[-1] = lines[-1].rstrip(",")
    lines.append(f"{indent}]")
    return "\n".join(lines) + "\n"


def replace_hosts_in_toml(content: str, new_block: str) -> str:
    dns_header = re.search(r"^\[dns\]\s*$", content, re.MULTILINE)
    if not dns_header:
        return content.rstrip() + "\n\n[dns]\n" + new_block

    section_start = dns_header.end()
    next_section = re.search(r"^\[.+\]\s*$", content[section_start:], re.MULTILINE)
    section_end = section_start + next_section.start() if next_section else len(content)

    dns_content = content[section_start:section_end]
    pattern = re.compile(r"(?ms)^\s*hosts\s*=\s*\[.*?\]\s*$", re.MULTILINE)

    if pattern.search(dns_content):
        new_dns_content = pattern.sub(new_block.rstrip() + "\n", dns_content)
    else:
        new_dns_content = dns_content.rstrip() + "\n\n" + new_block

    return content[:section_start] + new_dns_content + content[section_end:]


# ----------------------------- Mikrotik RSC ----------------------------------

def deploy_mikrotik_script(
    filename: str,
    lines: List[str],
    *,
    host: str,
    user: str,
    port: str,
    password: Optional[str],
    dry_run: bool,
    keep_files: bool,
) -> None:
    content = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    if dry_run:
        print(f"  [Dry Run] Generated local file: {filename}")
        return

    remote_user_host = f"{user}@{host}" if user else host
    remote_rsc_path = os.path.basename(filename)

    rc, _, err = scp_to_remote(filename, remote_user_host, remote_rsc_path, ssh_port=port, password=password, dry_run=dry_run)
    if rc != 0:
        print(f"  Error copying file: {err}")
        return

    import_cmd = f"/import file-name={remote_rsc_path}; /file remove [find name=\"{remote_rsc_path}\"]"
    rc_run, out_run, err_run = ssh_run(remote_user_host, import_cmd, ssh_port=port, password=password, dry_run=dry_run)
    if rc_run == 0:
        print(f"  Success: Imported {os.path.basename(filename)} on {host}")
    else:
        print(f"  Error running import on Mikrotik (RC={rc_run}):")
        if out_run.strip():
            print(f"    STDOUT: {out_run.strip()}")
        if err_run.strip():
            print(f"    STDERR: {err_run.strip()}")

    if not keep_files and os.path.exists(filename):
        os.unlink(filename)


# ----------------------------- SoT indexing ----------------------------------

def _normalize_asset_interfaces(asset: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Supports both schemas:
      - new: asset.interfaces[]
      - old: asset.vlan_id + asset.ip
    """
    if isinstance(asset.get("interfaces"), list) and asset["interfaces"]:
        out = []
        for iface in asset["interfaces"]:
            if not isinstance(iface, dict):
                continue
            out.append({
                "if_id": iface.get("if_id"),
                "vlan_id": iface.get("vlan_id"),
                "ip": iface.get("ip"),
                "mac": iface.get("mac"),
                "dns_provider": iface.get("dns_provider"),
            })
        return out

    # fallback (single iface)
    return [{
        "if_id": asset.get("vlan_id") or "default",
        "vlan_id": asset.get("vlan_id"),
        "ip": asset.get("ip"),
        "mac": asset.get("mac"),
        "dns_provider": asset.get("dns_provider"),
    }]


def _is_dynamic_ip(ip: Optional[str]) -> bool:
    if ip is None:
        return True
    s = str(ip).strip().lower()
    return s == "" or s == "dynamic"


def pick_asset_ip(
    asset: Dict[str, Any],
    *,
    vlan_id: Optional[str] = None,
    if_id: Optional[str] = None,
) -> Optional[str]:
    ifaces = _normalize_asset_interfaces(asset)

    if if_id:
        for iface in ifaces:
            if iface.get("if_id") == if_id and not _is_dynamic_ip(iface.get("ip")):
                return str(iface.get("ip")).strip()
        return None

    if vlan_id:
        for iface in ifaces:
            if iface.get("vlan_id") == vlan_id and not _is_dynamic_ip(iface.get("ip")):
                return str(iface.get("ip")).strip()

    for iface in ifaces:
        if not _is_dynamic_ip(iface.get("ip")):
            return str(iface.get("ip")).strip()

    return None


def service_backend_ip(service: Dict[str, Any], assets_by_id: Dict[str, Dict[str, Any]]) -> Optional[str]:
    backend = service.get("backend") or {}
    if isinstance(backend, dict) and backend.get("ip"):
        return str(backend["ip"]).strip()
    asset_id = service.get("asset_id")
    vlan_id = service.get("vlan_id")
    if asset_id and asset_id in assets_by_id:
        return pick_asset_ip(assets_by_id[asset_id], vlan_id=vlan_id)
    return None


def service_backend_port(service: Dict[str, Any]) -> Optional[int]:
    backend = service.get("backend") or {}
    if isinstance(backend, dict) and backend.get("port"):
        try:
            return int(backend["port"])
        except Exception:
            pass

    ports = service.get("ports") or {}
    service_ports = ports.get("service_ports")
    normalized = normalize_ports(service_ports)
    if normalized:
        return int(normalized[0]["port"])
    return None


def normalize_ports(value: Any) -> List[Dict[str, Any]]:
    """
    Accepts either:
      - list of {port:int, proto:tcp|udp}
      - string like "80/TCP, 443/TCP"
    """
    if value is None:
        return []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict) and "port" in item:
                proto = str(item.get("proto") or "tcp").lower()
                proto = "udp" if proto == "udp" else "tcp"
                out.append({"port": int(item["port"]), "proto": proto})
        return out
    if isinstance(value, str):
        return _parse_ports_str(value)
    return []


def _parse_ports_str(s: str) -> List[Dict[str, Any]]:
    s = s.strip()
    if not s:
        return []
    out: List[Dict[str, Any]] = []
    seen = set()
    for token in [t.strip() for t in s.split(",") if t.strip()]:
        if "/" in token:
            p, proto = token.split("/", 1)
            proto = proto.strip().lower()
        else:
            p, proto = token, "tcp"
        proto = "udp" if proto == "udp" else "tcp"
        if not p.strip().isdigit():
            continue
        key = (int(p.strip()), proto)
        if key in seen:
            continue
        seen.add(key)
        out.append({"port": int(p.strip()), "proto": proto})
    return out


# ----------------------------- VLAN server resolution -------------------------

def vlans_lookup(vlans_doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Returns:
      - globals: dict
      - vlans_by_id: dict[vlan_id] -> vlan entry
    """
    if not vlans_doc or not isinstance(vlans_doc, dict):
        return {"globals": {}, "vlans_by_id": {}}
    globals_ = vlans_doc.get("globals") or {}
    vlans = vlans_doc.get("vlans") or []
    by_id = {}
    if isinstance(vlans, list):
        for v in vlans:
            if isinstance(v, dict) and v.get("vlan_id"):
                by_id[str(v["vlan_id"]).lower()] = v
    return {"globals": globals_ if isinstance(globals_, dict) else {}, "vlans_by_id": by_id}


def resolve_vlan_server(
    vlan_id: str,
    *,
    want_type: str,  # "pihole" or "mikrotik"
    vlans_doc: Optional[Dict[str, Any]],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Returns a server dict with at least:
      host, user, port, use_sudo (for pihole), type
    Priority:
      1) data/vlans.yaml vlans[].servers if dns_type matches want_type
      2) dns-config.toml servers.<vlan_id> if type matches want_type
      3) empty dict
    """
    vlan_key = vlan_id.lower()

    lookup = vlans_lookup(vlans_doc)
    v = lookup["vlans_by_id"].get(vlan_key)
    if v and isinstance(v, dict):
        servers = v.get("servers") or {}
        if isinstance(servers, dict):
            dns_type = str(servers.get("dns_type") or "").lower()
            if dns_type == want_type:
                return {
                    "host": servers.get("dns_host"),
                    "user": servers.get("ssh_user"),
                    "port": str(servers.get("ssh_port") or "22"),
                    "use_sudo": bool(servers.get("use_sudo", True)),
                    "type": dns_type,
                }

    servers_cfg = (config.get("servers") or {})
    if isinstance(servers_cfg, dict):
        sc = servers_cfg.get(vlan_key) or servers_cfg.get(vlan_id) or {}
        if isinstance(sc, dict):
            t = str(sc.get("type") or "").lower()
            if t == want_type:
                return {
                    "host": sc.get("host"),
                    "user": sc.get("user"),
                    "port": str(sc.get("port") or "22"),
                    "use_sudo": bool(sc.get("use_sudo", config.get("use_sudo", True))),
                    "type": t,
                }

    return {}


def inherited_provider_for_vlan(vlan_id: str, *, vlans_doc: Optional[Dict[str, Any]]) -> str:
    lookup = vlans_lookup(vlans_doc)
    v = lookup["vlans_by_id"].get(vlan_id.lower())
    if not v:
        return "pihole"
    dns = v.get("dns") or {}
    if isinstance(dns, dict) and dns.get("default_provider"):
        p = str(dns["default_provider"]).lower()
        return p if p in ("pihole", "mikrotik") else "pihole"
    servers = v.get("servers") or {}
    if isinstance(servers, dict) and servers.get("dns_type"):
        p = str(servers["dns_type"]).lower()
        return p if p in ("pihole", "mikrotik") else "pihole"
    return "pihole"


# ----------------------------- DNS record derivation --------------------------

def iter_internal_dns_records(
    sot: Dict[str, Any],
    *,
    vlans_doc: Optional[Dict[str, Any]],
) -> Iterable[Dict[str, Any]]:
    """
    Yields dicts:
      { vlan_id, provider, fqdn, ip, comment }
    """
    assets_by_id: Dict[str, Dict[str, Any]] = sot["assets_by_id"]
    services_by_id: Dict[str, Dict[str, Any]] = sot["services_by_id"]
    dns_names: List[Dict[str, Any]] = sot["dns_names"]

    lookup = vlans_lookup(vlans_doc)
    globals_ = lookup["globals"]
    user_vlan = str(globals_.get("user_vlan") or "").lower() or None
    publish_to_user = bool(globals_.get("access_publish_to_user_vlan", False))

    for dn in dns_names:
        if not isinstance(dn, dict):
            continue
        internal = dn.get("internal") or {}
        if not isinstance(internal, dict):
            continue
        if internal.get("enabled") is not True:
            continue

        fqdn = str(dn.get("fqdn") or "").strip()
        if not fqdn:
            continue

        targets = dn.get("targets") or {}
        if not isinstance(targets, dict):
            continue

        addr_mode = str(internal.get("address") or "").strip() or "asset_ip"
        provider_mode = str(internal.get("provider") or "inherit_vlan").lower()

        base_vlan_id: Optional[str] = None
        ip: Optional[str] = None

        # Asset-target record
        asset_id = targets.get("asset_id")
        service_id = targets.get("service_id")

        if asset_id:
            asset = assets_by_id.get(str(asset_id))
            if not asset:
                continue

            if addr_mode == "asset_interface_ip":
                if_id = internal.get("interface_id")
                if not if_id:
                    continue
                ip = pick_asset_ip(asset, if_id=str(if_id))
                # base vlan id from interface metadata if present
                for iface in _normalize_asset_interfaces(asset):
                    if iface.get("if_id") == str(if_id):
                        base_vlan_id = str(iface.get("vlan_id") or "").lower() or None
                        break
                if base_vlan_id is None:
                    base_vlan_id = str(asset.get("vlan_id") or "").lower() or None
            else:
                ip = pick_asset_ip(asset)
                # pick first interface vlan_id
                ifaces = _normalize_asset_interfaces(asset)
                base_vlan_id = str((ifaces[0].get("vlan_id") if ifaces else asset.get("vlan_id")) or "").lower() or None

            comment = f"{dn.get('kind','dns')}: {asset.get('hostname') or asset_id}"

        # Service-target record
        elif service_id:
            service = services_by_id.get(str(service_id))
            if not service:
                continue

            base_vlan_id = str(service.get("vlan_id") or "").lower() or None
            backend_ip = service_backend_ip(service, assets_by_id)
            internal_target = None
            routing = service.get("routing") or {}
            if isinstance(routing, dict):
                internal_target = routing.get("internal_dns_target")

            if addr_mode == "routing_internal_dns_target":
                ip = str(internal_target).strip() if internal_target else backend_ip
            else:
                # default to service backend
                ip = backend_ip

            comment = f"{dn.get('kind','dns')}: {service.get('name') or service_id}"

        else:
            continue

        if not base_vlan_id or not ip:
            continue

        # Publish scopes
        publish_scopes = internal.get("publish_scopes")
        publish_vlans = []
        if isinstance(publish_scopes, list) and publish_scopes:
            for scope in publish_scopes:
                s = str(scope).lower()
                if s == "self":
                    publish_vlans.append(base_vlan_id)
                elif s == "user_vlan_if_enabled" and user_vlan and publish_to_user:
                    # only makes sense if we have an internal target IP pattern
                    publish_vlans.append(user_vlan)
        else:
            publish_vlans = [base_vlan_id]

        # Provider per publish vlan
        for vlan_id in dict.fromkeys(publish_vlans).keys():  # unique, preserve order
            if provider_mode in ("pihole", "mikrotik"):
                provider = provider_mode
            else:
                provider = inherited_provider_for_vlan(vlan_id, vlans_doc=vlans_doc)

            record_type = str(internal.get("record_type") or "A").strip().upper()
            if record_type not in ("A", "CNAME"):
                continue

            if record_type == "CNAME":
                cname_target = str(internal.get("cname_target") or internal.get("cname") or "").strip()
                if not cname_target:
                    continue
                value = cname_target
            else:
                value = ip

            for vlan_id in dict.fromkeys(publish_vlans).keys():
                if provider_mode in ("pihole", "mikrotik"):
                    provider = provider_mode
                else:
                    provider = inherited_provider_for_vlan(vlan_id, vlans_doc=vlans_doc)

                out = {
                    "vlan_id": vlan_id,
                    "provider": provider,
                    "fqdn": fqdn,
                    "record_type": record_type,
                    "value": value,
                    "comment": comment,
                }
                if record_type == "A":
                    out["ip"] = value  # backward compat
                else:
                    out["cname_target"] = value
                yield out


def iter_cloudflare_records(sot: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """
    Yields dicts suitable for DNSControl JSON, similar to the monolith:
      { name, target, proxied, domain }
    """
    for dn in sot["dns_names"]:
        if not isinstance(dn, dict):
            continue
        external = dn.get("external") or {}
        if not isinstance(external, dict) or external.get("enabled") is not True:
            continue
        if str(external.get("provider") or "").lower() != "cloudflare":
            continue

        fqdn = str(dn.get("fqdn") or "").strip()
        if not fqdn:
            continue

        cf = dn.get("cloudflare") or {}
        if not isinstance(cf, dict):
            continue
        target = str(cf.get("target_ip") or "").strip()
        if not target:
            continue

        proxied = None
        if "proxied" in external:
            proxied = bool(external.get("proxied"))
        else:
            ps = str(cf.get("proxy_status") or "").lower()
            proxied = ps in ("proxied", "on", "true", "yes", "1")

        # naive SLD.TLD extraction to match your current behavior
        domain = ".".join(fqdn.split(".")[-2:])

        yield {
            "name": fqdn,
            "target": target,
            "proxied": bool(proxied),
            "domain": domain,
        }


# ----------------------------- Caddyfile update -------------------------------

def find_closing_brace(text: str, start_index: int) -> int:
    depth = 1
    for i, ch in enumerate(text[start_index:], start=start_index):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def update_caddyfile_map(content: str, records: List[Dict[str, str]], generator_tag: str) -> str:
    """
    Updates map {host} {backend} blocks like the monolith does.
    Returns updated content string.
    """
    if not records:
        return content

    site_start_re = re.compile(r"(?m)^([^#\s{][^\s{]*(?:[ \t,]+[^\s{]+)*)\s+\{")

    blocks = []
    for match in site_start_re.finditer(content):
        domain_str = match.group(1)
        start_idx = match.end()
        end_idx = find_closing_brace(content, start_idx)
        if end_idx == -1:
            continue
        block_content = content[start_idx:end_idx]
        map_match = re.search(r"(map\s+\{host\}\s+\{backend\}\s+\{)(.*?)(\n\s+\})", block_content, re.DOTALL)
        if not map_match:
            continue

        domains = []
        for d in re.split(r"[ \t,]+", domain_str):
            d = d.strip()
            if not d:
                continue
            domains.append(d[2:] if d.startswith("*.") else d)

        blocks.append({
            "domains": domains,
            "map_match": map_match,
            "block_start": start_idx,
            "block_end": end_idx,
        })

    if not blocks:
        raise RuntimeError("No 'map {host} {backend}' blocks found in Caddyfile.")

    block_records = {i: [] for i in range(len(blocks))}
    for r in records:
        fqdn = r["host"]
        best = -1
        best_len = -1
        for i, b in enumerate(blocks):
            for d in b["domains"]:
                if fqdn == d or fqdn.endswith("." + d):
                    if len(d) > best_len:
                        best_len = len(d)
                        best = i
        if best != -1:
            block_records[best].append(r)

    edits = []
    for i, b in enumerate(blocks):
        recs = block_records[i]
        if not recs:
            continue
        max_host_len = max(len(r["host"]) for r in recs)
        indent = "        "
        lines = []
        for r in recs:
            host = r["host"]
            backend = r["backend"]
            padding = " " * (max_host_len - len(host) + 4)
            lines.append(f"{indent}{host}{padding}{backend}")
        new_map_body = "\n".join(lines)

        mm = b["map_match"]
        existing_map_body = mm.group(2)
        has_default = "default" in existing_map_body and "unknown" in existing_map_body

        repl = (
            f"{mm.group(1)}\n"
            f"{indent}# {generator_tag} on {datetime.datetime.now()}\n"
            f"{new_map_body}\n"
        )
        if has_default:
            repl += f"\n{indent}default                 unknown"
        repl += mm.group(3)

        abs_start = b["block_start"] + mm.start()
        abs_end = b["block_start"] + mm.end()
        edits.append((abs_start, abs_end, repl))

    edits.sort(key=lambda x: x[0], reverse=True)
    new_content = content
    for start, end, repl in edits:
        new_content = new_content[:start] + repl + new_content[end:]
    return new_content

def build_cname_records_block(entries: List[Dict[str, Any]], *, indent: str = "") -> str:
    """
    entries: [{ "fqdn": "<alias>", "target": "<canonical>" }]
    Pi-hole expects: "alias,target[,TTL]"
    """
    unique = {(e["fqdn"], e["target"]) for e in entries}
    lines = [f"{indent}cnameRecords = ["]
    for alias, target in sorted(unique):
        lines.append(f'{indent}  "{alias},{target}",')
    if len(lines) > 1:
        lines[-1] = lines[-1].rstrip(",")
    lines.append(f"{indent}]")
    return "\n".join(lines) + "\n"


def replace_cname_records_in_toml(content: str, new_block: str) -> str:
    dns_header = re.search(r"^\[dns\]\s*$", content, re.MULTILINE)
    if not dns_header:
        return content.rstrip() + "\n\n[dns]\n" + new_block

    section_start = dns_header.end()
    next_section = re.search(r"^\[.+\]\s*$", content[section_start:], re.MULTILINE)
    section_end = section_start + next_section.start() if next_section else len(content)

    dns_content = content[section_start:section_end]
    pattern = re.compile(r"(?ms)^\s*cnameRecords\s*=\s*\[.*?\]\s*$", re.MULTILINE)

    if pattern.search(dns_content):
        new_dns_content = pattern.sub(new_block.rstrip() + "\n", dns_content)
    else:
        new_dns_content = dns_content.rstrip() + "\n\n" + new_block

    return content[:section_start] + new_dns_content + content[section_end:]
