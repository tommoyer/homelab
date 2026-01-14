from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple

from .common import (
    SSHSpec,
    ensure_dir,
    scp_download,
    scp_upload,
    ssh_run,
    unified_diff_text,
)
from .sot import load_sot


BEGIN_MARK = "# === NETOPS_SOT:BEGIN ==="
END_MARK = "# === NETOPS_SOT:END ==="


def _strip_dot(s: str) -> str:
    return s[:-1] if s.endswith(".") else s


def _extract_global_block(caddyfile_text: str) -> str:
    # Preserve a leading global options block: { ... } at the very top
    m = re.match(r"(?s)^\s*\{\s*.*?\n\}\s*\n+", caddyfile_text)
    return m.group(0) if m else ""


def _replace_or_insert_generated_region(existing: str, generated: str, global_block: str) -> str:
    if BEGIN_MARK in existing and END_MARK in existing:
        pre, rest = existing.split(BEGIN_MARK, 1)
        _, post = rest.split(END_MARK, 1)
        # preserve everything outside markers (including global block and any custom content)
        return pre.rstrip() + "\n\n" + generated.strip() + "\n\n" + post.lstrip()

    # no markers: keep global block (if any) and replace everything else
    return global_block.rstrip() + "\n\n" + generated.strip() + "\n"


def _domains_from_yaml(sot) -> List[str]:
    # Prefer explicit configured domains if you add them later:
    # globals.domains: [ ... ]
    vdoc_domains = []
    # if you add globals.domains in the future, this will be picked up by sot parsing changes
    # For now, derive from known suffixes by inspecting vlans raw (available via sot.vlans + original yaml not stored).
    # Practical approach: derive from fqdn set (most reliable) by taking “all suffixes that appear in via_caddy hostnames”
    return vdoc_domains


def _fqdn_domains(sot) -> List[str]:
    # Domains are the set of suffixes you intend Caddy to handle.
    # Since you said “only those configured in YAML”, derive from VLAN suffixes if present in vlans.yaml.
    # If suffixes aren’t available, fall back to the set of base domains inferred from DNS names that route via Caddy.
    domains: set[str] = set()

    # 1) base_domain if present
    if sot.globals.base_domain:
        domains.add(_strip_dot(sot.globals.base_domain))

    # 2) try to pull suffixes from the vlan objects if your sot parser includes them later
    # (not required; safe to ignore)

    # 3) infer from fqdn endings of via_caddy services (best-effort)
    via_caddy_fqdns = []
    for dn in sot.dns_names.values():
        if not dn.targets.service_id:
            continue
        svc = sot.services[dn.targets.service_id]
        if not svc.routing.via_caddy:
            continue
        via_caddy_fqdns.append(_strip_dot(dn.fqdn))

    # If base_domain was set, it’s probably sufficient.
    # Otherwise, infer domains as “last 2 labels” ONLY if needed; error if we can’t match.
    if domains:
        return sorted(domains, key=len, reverse=True)

    inferred: set[str] = set()
    for fqdn in via_caddy_fqdns:
        parts = fqdn.split(".")
        if len(parts) >= 2:
            inferred.add(".".join(parts[-2:]))
    return sorted(inferred, key=len, reverse=True)


def _assign_domain(fqdn: str, domains: List[str]) -> str:
    fqdn = _strip_dot(fqdn)
    for d in domains:
        d = _strip_dot(d)
        if fqdn == d or fqdn.endswith("." + d):
            return d
    raise ValueError(f"FQDN {fqdn} is not under any configured domain: {domains}")


def _service_backend_ip(sot, service) -> str:
    if service.backend.ip:
        return service.backend.ip

    asset = sot.assets[service.asset_id]
    for itf in asset.interfaces:
        if itf.if_id == service.interface_id:
            if itf.ip == "dynamic":
                raise ValueError(f"Service {service.service_id}: asset interface IP is dynamic")
            return itf.ip

    raise ValueError(f"Service {service.service_id}: unable to resolve backend IP from asset/interface")


def _build_caddy_generation(sot) -> str:
    if not sot.globals.caddy_ip:
        raise ValueError("globals.caddy_ip is required to generate the health endpoint block")

    domains = _fqdn_domains(sot)
    if not domains:
        raise ValueError("No domains found to generate Caddy site blocks (base_domain empty and no via_caddy hostnames)")

    # Collect host->backend mappings for via_caddy services
    # Enforce port present (required)
    host_entries: List[Tuple[str, str, str, bool]] = []
    # (fqdn, backend_ip:port, domain, tls_insecure_skip_verify)
    for dn in sot.dns_names.values():
        if not dn.targets.service_id:
            continue

        svc = sot.services[dn.targets.service_id]
        if not svc.routing.via_caddy:
            continue

        if svc.routing.caddy_port is None:
            raise ValueError(f"Service {svc.service_id}: routing.caddy_port is required when routing.via_caddy is true")

        backend_ip = _service_backend_ip(sot, svc)
        backend = f"{backend_ip}:{int(svc.routing.caddy_port)}"
        fqdn = _strip_dot(dn.fqdn)
        dom = _assign_domain(fqdn, domains)

        tls_skip = bool(svc.routing.tls_insecure_skip_verify)
        host_entries.append((fqdn, backend, dom, tls_skip))

    # Deduplicate exact hosts (fqdn unique; if duplicates with different backend, raise)
    by_host: Dict[str, Tuple[str, str, bool]] = {}
    for fqdn, backend, dom, tls_skip in host_entries:
        if fqdn in by_host:
            prev_backend, prev_dom, prev_tls = by_host[fqdn]
            if prev_backend != backend or prev_dom != dom or prev_tls != tls_skip:
                raise ValueError(f"Host {fqdn} defined multiple times with different backends/settings")
        by_host[fqdn] = (backend, dom, tls_skip)

    # Assign each fqdn to the most-specific matching domain to avoid overlap between e.g. foo.bar.com and bar.com
    domains_sorted = sorted(domains, key=len, reverse=True)
    hosts_by_domain: Dict[str, List[str]] = {d: [] for d in domains_sorted}
    for fqdn in sorted(by_host.keys()):
        dom = _assign_domain(fqdn, domains_sorted)
        hosts_by_domain[dom].append(fqdn)

    # Build special-case matchers per domain for tls skip verify
    # Group by domain and service settings; matcher is host list that requires https+skip
    tls_skip_hosts_by_domain: Dict[str, List[str]] = {d: [] for d in domains_sorted}
    for fqdn, (backend, dom, tls_skip) in by_host.items():
        if tls_skip:
            tls_skip_hosts_by_domain[dom].append(fqdn)

    # Generated file
    lines: List[str] = []
    lines.append(BEGIN_MARK)
    lines.append("# AUTOGENERATED by netops_push/update_caddy.py")
    lines.append("# Do not edit between NETOPS_SOT markers; edit YAML SOT instead.")
    lines.append(END_MARK)
    lines.append("")

    # Site blocks
    for dom in domains_sorted:
        hosts = hosts_by_domain.get(dom, [])
        if not hosts:
            # still generate the block if configured domain exists, but it will always 404
            pass

        lines.append("# ------------------------------------------------------------------")
        lines.append(f"# AUTOGENERATED: Public Wildcard Handler ({dom})")
        lines.append("# ------------------------------------------------------------------")
        lines.append(f"*.{dom} {dom} {{")
        lines.append("    # AUTOGENERATED: Cloudflare DNS Challenge for Wildcard Certs")
        lines.append("    tls {")
        lines.append("        dns cloudflare {env.CLOUDFLARE_API_TOKEN}")
        lines.append("    }")
        lines.append("")
        lines.append("    # AUTOGENERATED: Redirect www.<domain> to apex")
        lines.append(f"    @www host www.{dom}")
        lines.append("    handle @www {")
        lines.append(f"        redir https://{dom}{{uri}} permanent")
        lines.append("    }")
        lines.append("")
        lines.append("    # AUTOGENERATED: Service Map (Hostname -> Backend IP:Port)")
        lines.append("    map {host} {backend} {")
        for fqdn in hosts:
            backend, _, _tls_skip = by_host[fqdn]
            lines.append(f"        {fqdn} {backend}")
        lines.append('        default "unknown"')
        lines.append("    }")
        lines.append("")

        # Special-case TLS skip verify handler(s)
        skip_hosts = sorted(tls_skip_hosts_by_domain.get(dom, []))
        if skip_hosts:
            lines.append("    # AUTOGENERATED: Special-case backends (HTTPS + tls_insecure_skip_verify)")
            lines.append(f"    @tls_skip host {' '.join(skip_hosts)}")
            lines.append("    handle @tls_skip {")
            lines.append("        reverse_proxy https://{backend} {")
            lines.append("            transport http {")
            lines.append("                tls_insecure_skip_verify")
            lines.append("            }")
            lines.append("        }")
            lines.append("    }")
            lines.append("")

        lines.append('    # AUTOGENERATED: Default mapped reverse proxy')
        lines.append('    @mapped expression {backend} != "unknown"')
        lines.append("    handle @mapped {")
        lines.append("        reverse_proxy {backend}")
        lines.append("    }")
        lines.append("")
        lines.append("    handle {")
        lines.append('        respond "Service not defined in Caddy Map" 404')
        lines.append("    }")
        lines.append("}")
        lines.append("")

    # Health endpoint (matches your current pattern)
    lines.append("# ------------------------------------------------------------------")
    lines.append("# AUTOGENERATED: Health endpoint")
    lines.append("# ------------------------------------------------------------------")
    lines.append(f"http://{sot.globals.caddy_ip} {{")
    lines.append('    respond /healthz "ok" 200')
    lines.append('    respond "not found" 404')
    lines.append("}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Update Caddyfile from SOT YAML (fetch, generate, diff, push, restart).")
    ap.add_argument("--assets", required=True, type=Path)
    ap.add_argument("--dns-names", required=True, type=Path)
    ap.add_argument("--services", required=True, type=Path)
    ap.add_argument("--vlans", required=True, type=Path)

    ap.add_argument("--cache-dir", default=Path("cache"), type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--identity-file", default=None)

    args = ap.parse_args()

    sot = load_sot(
        assets_path=args.assets,
        dns_names_path=args.dns_names,
        services_path=args.services,
        vlans_path=args.vlans,
    )

    if not sot.globals.caddy:
        raise ValueError("vlans.yaml globals.caddy is required for Caddyfile updates")

    c = sot.globals.caddy
    if not c.ssh_host or not c.ssh_user or not c.caddyfile_path or not c.compose_dir:
        raise ValueError("globals.caddy must include ssh_host, ssh_user, caddyfile_path, compose_dir")

    spec = SSHSpec(
        host=c.ssh_host,
        user=c.ssh_user,
        port=int(c.ssh_port),
        use_sudo=bool(c.use_sudo),
        identity_file=args.identity_file,
    )

    cache_root = args.cache_dir / "caddy"
    ensure_dir(cache_root)

    downloaded = cache_root / "Caddyfile"
    generated = cache_root / "Caddyfile.generated"

    # fetch
    scp_download(spec, c.caddyfile_path, downloaded)
    old = downloaded.read_text(encoding="utf-8")
    global_block = _extract_global_block(old)

    # generate
    generated_region = _build_caddy_generation(sot)
    new = _replace_or_insert_generated_region(old, generated_region, global_block)
    generated.write_text(new, encoding="utf-8")

    diff = unified_diff_text(old, new, f"{spec.host}:{c.caddyfile_path}", f"{spec.host}:{c.caddyfile_path}(updated)")
    changed = bool(diff)

    if args.dry_run:
        if changed:
            print(diff, end="" if diff.endswith("\n") else "\n")
        else:
            print("No changes.")
        return 0

    if not changed:
        print("No changes; skipping upload/restart.")
        return 0

    # push (upload temp + install)
    remote_tmp = "/tmp/Caddyfile.netops_sot"
    scp_upload(spec, generated, remote_tmp)

    install_cmd = f"install -m 0644 {remote_tmp} {c.caddyfile_path}"
    restart_cmd = f'cd "{c.compose_dir}" && docker compose restart'

    if spec.use_sudo:
        ssh_run(spec, f"sudo {install_cmd}")
        ssh_run(spec, f"sudo rm -f {remote_tmp}")
        ssh_run(spec, f"sudo {restart_cmd}")
    else:
        ssh_run(spec, install_cmd)
        ssh_run(spec, f"rm -f {remote_tmp}")
        ssh_run(spec, restart_cmd)

    print("Caddyfile updated and docker compose restarted.")

    if (not args.keep) and (not args.dry_run):
        for p in cache_root.glob("Caddyfile*"):
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

