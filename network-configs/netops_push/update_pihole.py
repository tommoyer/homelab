from __future__ import annotations

import argparse
import re
from pathlib import Path

from .common import SSHSpec, ensure_dir, scp_download, scp_upload, ssh_run, unified_diff_text
from .sot import build_pihole_records_by_vlan, load_sot


REMOTE_PIHOLE_TOML = "/etc/pihole/pihole.toml"
RELOAD_CMD = "pihole reloaddns"


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _format_toml_string_array(key: str, values: list[str]) -> str:
    lines = [f"{key} = ["]
    for v in values:
        lines.append(f'  "{_toml_escape(v)}",')
    lines.append("]")
    return "\n".join(lines) + "\n"


def _update_dns_section(content: str, hosts: list[str], cnames: list[str]) -> str:
    dns_hdr = re.search(r"(?m)^\[dns\]\s*$", content)
    if not dns_hdr:
        raise ValueError("No [dns] section found in pihole.toml")

    start = dns_hdr.start()
    after_hdr = dns_hdr.end()

    next_tbl = re.search(r"(?m)^\[.+\]\s*$", content[after_hdr:])
    end = after_hdr + (next_tbl.start() if next_tbl else len(content[after_hdr:]))

    dns_block = content[after_hdr:end]

    hosts_block = _format_toml_string_array("hosts", hosts)
    cnames_block = _format_toml_string_array("cnameRecords", cnames)

    def replace_or_insert(block: str, key: str, new_block: str) -> str:
        pat = re.compile(rf"(?ms)^\s*{re.escape(key)}\s*=\s*\[.*?\]\s*(?:\n|$)")
        if pat.search(block):
            return pat.sub(new_block, block, count=1)
        # insert right after header (i.e., at top of dns table)
        prefix = "\n" if (block and not block.startswith("\n")) else ""
        return new_block + prefix + block

    dns_block = replace_or_insert(dns_block, "hosts", hosts_block)
    dns_block = replace_or_insert(dns_block, "cnameRecords", cnames_block)

    return content[:after_hdr] + dns_block + content[end:]


def main() -> int:
    ap = argparse.ArgumentParser(description="Update Pi-hole v6 pihole.toml dns.hosts + dns.cnameRecords from SOT YAML.")
    ap.add_argument("--assets", required=True, type=Path)
    ap.add_argument("--dns-names", required=True, type=Path)
    ap.add_argument("--services", required=True, type=Path)
    ap.add_argument("--vlans", required=True, type=Path)

    ap.add_argument("--cache-dir", default=Path("cache"), type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--identity-file", default=None)
    ap.add_argument("--vlan-id", default=None, help="Optional: process only one VLAN (debug)")

    args = ap.parse_args()

    sot = load_sot(
        assets_path=args.assets,
        dns_names_path=args.dns_names,
        services_path=args.services,
        vlans_path=args.vlans,
    )

    desired = build_pihole_records_by_vlan(sot)

    if args.vlan_id:
        desired = {k: v for k, v in desired.items() if k == args.vlan_id}

    cache_root = args.cache_dir / "pihole"
    ensure_dir(cache_root)

    all_ok = True

    for vlan_id, recs in desired.items():
        vlan = sot.vlans.get(vlan_id)
        if not vlan or not vlan.servers:
            raise ValueError(f"VLAN {vlan_id}: missing servers block for pihole SSH access")
        if vlan.servers.dns_type != "pihole":
            continue
        if not vlan.servers.dns_host:
            raise ValueError(f"VLAN {vlan_id}: servers.dns_host is empty")

        spec = SSHSpec(
            host=vlan.servers.dns_host,
            user=vlan.servers.ssh_user,
            port=vlan.servers.ssh_port,
            use_sudo=vlan.servers.use_sudo,
            identity_file=args.identity_file,
        )

        vlan_dir = cache_root / vlan_id
        ensure_dir(vlan_dir)
        downloaded = vlan_dir / "pihole.toml"
        generated = vlan_dir / "pihole.toml.generated"

        # download (overwrite in place)
        scp_download(spec, REMOTE_PIHOLE_TOML, downloaded)
        old = downloaded.read_text(encoding="utf-8")

        new = _update_dns_section(old, recs["hosts"], recs["cnames"])
        generated.write_text(new, encoding="utf-8")

        diff = unified_diff_text(old, new, f"{vlan_id}:/etc/pihole/pihole.toml", f"{vlan_id}:/etc/pihole/pihole.toml(updated)")
        changed = bool(diff)

        if args.dry_run:
            if changed:
                print(diff, end="" if diff.endswith("\n") else "\n")
            else:
                print(f"[{vlan_id}] No changes.")
            continue

        if not changed:
            print(f"[{vlan_id}] No changes; skipping upload/reload.")
            continue

        # upload to temp, then install into place
        remote_tmp = "/tmp/pihole.toml.netops_sot"
        scp_upload(spec, generated, remote_tmp)

        if spec.use_sudo:
            ssh_run(spec, f"sudo install -m 0644 {remote_tmp} {REMOTE_PIHOLE_TOML}")
            ssh_run(spec, f"sudo {RELOAD_CMD}")
            ssh_run(spec, f"sudo rm -f {remote_tmp}")
        else:
            ssh_run(spec, f"install -m 0644 {remote_tmp} {REMOTE_PIHOLE_TOML}")
            ssh_run(spec, RELOAD_CMD)
            ssh_run(spec, f"rm -f {remote_tmp}")

        print(f"[{vlan_id}] Updated Pi-hole and reloaded DNS.")

    # cleanup only on full success and not keep
    if all_ok and (not args.keep) and (not args.dry_run):
        # remove per-vlan generated artifacts (keep directory structure)
        for p in cache_root.rglob("pihole.toml*"):
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

