#!/usr/bin/env python3
"""
apply_pihole.py

Applies internal DNS records (provider=pihole) to Pi-hole servers by updating:
  /etc/pihole/pihole.toml  [dns].hosts

Reads:
  data/assets.yaml, data/services.yaml, data/dns_names.yaml (+ optional data/vlans.yaml)

Uses:
  dns-config.toml for per-VLAN server host/user/port if not present in vlans.yaml.

Dry-run:
  writes files under ./dry-run/
"""

from __future__ import annotations

import argparse
import datetime
import os
from typing import Any, Dict, List

from netops_lib import (
    build_cname_records_block,
    build_hosts_block,
    check_prerequisites,
    iter_internal_dns_records,
    load_config_toml,
    load_sot,
    replace_cname_records_in_toml,
    replace_hosts_in_toml,
    resolve_vlan_server,
    scp_from_remote,
    scp_to_remote,
    ssh_run,
)


def process_vlan_pihole(
    vlan_id: str,
    entries: List[Dict[str, Any]],
    *,
    server: Dict[str, Any],
    global_cfg: Dict[str, Any],
    dry_run: bool,
    backup: bool,
    reload_cmd_arg: str | None,
    keep_files: bool,
) -> None:
    if not entries:
        return

    remote_host = server.get("host")
    if not remote_host:
        print(f"[Warning] No Pi-hole host for VLAN '{vlan_id}'. Skipping.")
        return

    ssh_user = server.get("user") or global_cfg.get("ssh_user", "root")
    ssh_port = str(server.get("port") or global_cfg.get("ssh_port", "22"))
    use_sudo = bool(server.get("use_sudo", global_cfg.get("use_sudo", True)))
    sudo_prefix = "sudo " if use_sudo else ""

    remote_path = "/etc/pihole/pihole.toml"
    remote_user_host = f"{ssh_user}@{remote_host}" if ssh_user else remote_host

    os.makedirs("dry-run", exist_ok=True) if dry_run else None

    local_name = f"pihole-{vlan_id}.toml"
    local_path = os.path.abspath(local_name)

    print(f"Updating Pi-hole for VLAN {vlan_id} on {remote_host} (User: {ssh_user})...")

    # 1) fetch
    rc, _, err = scp_from_remote(remote_user_host, remote_path, local_path, ssh_port=ssh_port, dry_run=dry_run)
    if rc != 0 and not dry_run:
        print(f"  [Warning] Could not fetch remote config: {err}")
        if not os.path.isfile(local_path):
            print(f"  [Error] No local copy of {local_name} found. Cannot proceed.")
            return
        print(f"  Using existing local copy: {local_path}")

    # 2) read/modify
    if os.path.isfile(local_path):
        with open(local_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "# Generated\n[dns]\nhosts = []\n"

    a_entries = []
    cname_entries = []

    for e in entries:
        rtype = str(e.get("record_type") or "A").upper()
        if rtype == "CNAME":
            cname_entries.append({"fqdn": e["fqdn"], "target": e["value"]})
        else:
            a_entries.append({"fqdn": e["fqdn"], "ip": e["value"]})

    hosts_block = build_hosts_block(a_entries)
    cname_block = build_cname_records_block(cname_entries)

    new_content = replace_hosts_in_toml(content, hosts_block)
    new_content = replace_cname_records_in_toml(new_content, cname_block)

    out_path = os.path.join("dry-run", local_name) if dry_run else local_path
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"  {'[Dry Run] ' if dry_run else ''}Wrote: {out_path}")

    if dry_run:
        return

    # 3) backup + push + reload
    remote_tmp = f"/tmp/pihole.toml.{os.getpid()}.{vlan_id}"
    if backup:
        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        backup_cmd = f"{sudo_prefix}cp {remote_path} {remote_path}.bak-{ts}"
        ssh_run(remote_user_host, backup_cmd, ssh_port=ssh_port, dry_run=dry_run)

    rc, _, err = scp_to_remote(out_path, remote_user_host, remote_tmp, ssh_port=ssh_port, dry_run=dry_run)
    if rc != 0:
        print(f"  Error copying file: {err}")
        return

    mv_cmd = (
        f"{sudo_prefix}mv {remote_tmp} {remote_path} && "
        f"{sudo_prefix}chown root:root {remote_path} && "
        f"{sudo_prefix}chmod 644 {remote_path}"
    )
    rc, _, err = ssh_run(remote_user_host, mv_cmd, ssh_port=ssh_port, dry_run=dry_run)
    if rc != 0:
        print(f"  Error moving file into place: {err}")
        return

    reload_cmd = reload_cmd_arg or f"{sudo_prefix}pihole restartdns"
    rc, _, err = ssh_run(remote_user_host, reload_cmd, ssh_port=ssh_port, dry_run=dry_run)
    if rc == 0:
        print(f"  Success: Reloaded DNS on {remote_host}")
    else:
        print(f"  Warning: Reload command failed: {err}")

    if not keep_files and os.path.exists(local_path):
        os.remove(local_path)
        print(f"  Cleaned up local file: {local_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--config", default="dns-config.toml")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--backup", action="store_true")
    ap.add_argument("--reload-cmd")
    ap.add_argument("--vlan", action="append", help="Limit to VLAN(s). Can be repeated.")
    ap.add_argument("--ssh-user")
    ap.add_argument("--ssh-port")
    ap.add_argument("--use-sudo", action="store_true", help="Force sudo on Pi-hole hosts")
    args = ap.parse_args()

    if not check_prerequisites(needs_dnscontrol=False):
        return 1

    sot = load_sot(args.data_dir)
    cfg, _ = load_config_toml(args.config)

    global_cfg = {
        "ssh_user": args.ssh_user or cfg.get("ssh_user", "root"),
        "ssh_port": args.ssh_port or cfg.get("ssh_port", 22),
        "use_sudo": bool(args.use_sudo or cfg.get("use_sudo", True)),
    }

    # collect pihole records
    vlan_filter = {v.lower() for v in args.vlan} if args.vlan else None
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for r in iter_internal_dns_records(sot, vlans_doc=sot.get("vlans_doc")):
        if r["provider"] != "pihole":
            continue
        vlan_id = r["vlan_id"].lower()
        if vlan_filter and vlan_id not in vlan_filter:
            continue
        grouped.setdefault(vlan_id, []).append(r)

    if not grouped:
        print("No Pi-hole records to apply.")
        return 0

    for vlan_id, entries in grouped.items():
        server = resolve_vlan_server(vlan_id, want_type="pihole", vlans_doc=sot.get("vlans_doc"), config=cfg)
        process_vlan_pihole(
            vlan_id,
            entries,
            server=server,
            global_cfg=global_cfg,
            dry_run=args.dry_run,
            backup=args.backup,
            reload_cmd_arg=args.reload_cmd,
            keep_files=args.keep,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
