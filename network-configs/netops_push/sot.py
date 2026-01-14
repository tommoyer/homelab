from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from .common import load_yaml_documents


COMMENT_PREFIX = "HOMELAB:SOT"


@dataclass(frozen=True)
class CaddyConfig:
    ssh_host: str
    ssh_user: str
    ssh_port: int = 22
    use_sudo: bool = False
    caddyfile_path: str = "/etc/caddy/Caddyfile"
    compose_dir: str = "/etc/caddy"


@dataclass(frozen=True)
class Globals:
    base_domain: str
    user_vlan: str
    access_publish_to_user_vlan: bool
    caddy_ip: str
    caddy: Optional[CaddyConfig] = None


# extend ServiceRouting
@dataclass(frozen=True)
class ServiceRouting:
    via_caddy: bool
    internal_dns_target: Optional[str] = None
    caddy_port: Optional[int] = None
    tls_insecure_skip_verify: bool = False
    caddy_scheme: Optional[str] = None

@dataclass(frozen=True)
class VlanServers:
    dns_host: str
    dns_type: str  # "pihole" or "mikrotik"
    ssh_user: str
    ssh_port: int = 22
    use_sudo: bool = False


@dataclass(frozen=True)
class VlanDNS:
    default_provider: str  # "pihole" or "mikrotik"
    include_access_fqdn: bool = True


@dataclass(frozen=True)
class Vlan:
    vlan_id: str
    vlan_tag: int
    cidr: Optional[str]
    dns: VlanDNS
    servers: Optional[VlanServers] = None


@dataclass(frozen=True)
class AssetInterface:
    if_id: str
    vlan_id: str
    ip: str  # may be "dynamic"


@dataclass(frozen=True)
class Asset:
    asset_id: str
    hostname: str
    interfaces: list[AssetInterface]


@dataclass(frozen=True)
class ServicePort:
    port: int
    proto: str  # "tcp"/"udp"
    backend_port: Optional[int] = None  # optional if your YAML supports it


@dataclass(frozen=True)
class ServicePorts:
    service_ports: list[ServicePort]
    firewall_ports: list[ServicePort]


@dataclass(frozen=True)
class ServiceBackend:
    ip: Optional[str]
    port: Optional[int]


@dataclass(frozen=True)
class Service:
    service_id: str
    name: str
    asset_id: str
    vlan_id: str
    interface_id: str
    ports: ServicePorts
    routing: ServiceRouting
    backend: ServiceBackend


@dataclass(frozen=True)
class DNSTargets:
    service_id: Optional[str]
    asset_id: Optional[str]


@dataclass(frozen=True)
class DNSInternal:
    enabled: bool
    provider: str
    address: str
    record_type: str  # "A" or "CNAME"
    publish_scopes: list[str]
    interface_id: Optional[str] = None
    target: Optional[str] = None  # for CNAME: explicit target if present


@dataclass(frozen=True)
class DNSExternal:
    enabled: bool
    provider: Optional[str] = None
    record_type: Optional[str] = None
    target: Optional[str] = None


@dataclass(frozen=True)
class CloudflareMeta:
    target_ip: Optional[str] = None
    proxy_status: Optional[str] = None  # "dns-only" or "proxied"


@dataclass(frozen=True)
class DNSName:
    dns_id: str
    kind: str  # "infra" or "access"
    fqdn: str
    targets: DNSTargets
    internal: DNSInternal
    external: DNSExternal
    cloudflare: Optional[CloudflareMeta] = None


@dataclass(frozen=True)
class SOT:
    globals: Globals
    vlans: dict[str, Vlan]
    assets: dict[str, Asset]
    services: dict[str, Service]
    dns_names: dict[str, DNSName]


def _as_list(x: Any) -> list[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _strip_dot(s: str) -> str:
    return s[:-1] if s.endswith(".") else s


def load_sot(*, assets_path: Path, dns_names_path: Path, services_path: Path, vlans_path: Path) -> SOT:
    # vlans
    vdocs = load_yaml_documents(vlans_path)
    if len(vdocs) != 1:
        raise ValueError("vlans input must produce exactly one document")
    vdoc = vdocs[0]
    g = vdoc.get("globals", {}) or {}
    glb = Globals(
        base_domain=str(g.get("base_domain", "")).strip(),
        user_vlan=str(g.get("user_vlan", "")).strip(),
        access_publish_to_user_vlan=bool(g.get("access_publish_to_user_vlan", False)),
        caddy_ip=str(g.get("caddy_ip", "")).strip(),
    )

    vlans: dict[str, Vlan] = {}
    for v in _as_list(vdoc.get("vlans", [])):
        dns = v.get("dns", {}) or {}
        servers = v.get("servers", None)
        servers_obj = None
        if isinstance(servers, dict):
            servers_obj = VlanServers(
                dns_host=str(servers.get("dns_host", "")).strip(),
                dns_type=str(servers.get("dns_type", "")).strip(),
                ssh_user=str(servers.get("ssh_user", "")).strip(),
                ssh_port=int(servers.get("ssh_port", 22)),
                use_sudo=bool(servers.get("use_sudo", False)),
            )
        vlan_obj = Vlan(
            vlan_id=str(v["vlan_id"]),
            vlan_tag=int(v["vlan_tag"]),
            cidr=v.get("cidr"),
            dns=VlanDNS(
                default_provider=str(dns.get("default_provider", "")).strip(),
                include_access_fqdn=bool(dns.get("include_access_fqdn", True)),
            ),
            servers=servers_obj,
        )
        vlans[vlan_obj.vlan_id] = vlan_obj

    # assets
    adocs = load_yaml_documents(assets_path)
    assets: dict[str, Asset] = {}
    for doc in adocs:
        for a in _as_list(doc.get("assets", [])):
            ifaces: list[AssetInterface] = []
            for itf in _as_list(a.get("interfaces", [])):
                ifaces.append(
                    AssetInterface(
                        if_id=str(itf["if_id"]),
                        vlan_id=str(itf["vlan_id"]),
                        ip=str(itf["ip"]),
                    )
                )
            asset_obj = Asset(
                asset_id=str(a["asset_id"]),
                hostname=str(a.get("hostname", a["asset_id"])),
                interfaces=ifaces,
            )
            assets[asset_obj.asset_id] = asset_obj

    # services
    sdocs = load_yaml_documents(services_path)
    services: dict[str, Service] = {}
    for doc in sdocs:
        for s in _as_list(doc.get("services", [])):
            ports = s.get("ports", {}) or {}
            sp = []
            fp = []
            for p in _as_list(ports.get("service_ports", [])):
                sp.append(ServicePort(port=int(p["port"]), proto=str(p["proto"]), backend_port=p.get("backend_port")))
            for p in _as_list(ports.get("firewall_ports", [])):
                fp.append(ServicePort(port=int(p["port"]), proto=str(p["proto"]), backend_port=p.get("backend_port")))
            routing = s.get("routing", {}) or {}
            backend = s.get("backend", {}) or {}
            svc = Service(
                service_id=str(s["service_id"]),
                name=str(s.get("name", s["service_id"])),
                asset_id=str(s["asset_id"]),
                vlan_id=str(s["vlan_id"]),
                interface_id=str(s["interface_id"]),
                ports=ServicePorts(service_ports=sp, firewall_ports=fp),
                routing=ServiceRouting(
                    via_caddy=bool(routing.get("via_caddy", False)),
                    internal_dns_target=routing.get("internal_dns_target"),
                    caddy_port=routing.get("caddy_port"),
                    tls_insecure_skip_verify=bool(routing.get("tls_insecure_skip_verify", False)),
                    caddy_scheme=routing.get("caddy_scheme"),
                ),
                backend=ServiceBackend(ip=backend.get("ip"), port=backend.get("port")),
            )
            services[svc.service_id] = svc

    # dns-names
    ndocs = load_yaml_documents(dns_names_path)
    dns_names: dict[str, DNSName] = {}
    for doc in ndocs:
        for d in _as_list(doc.get("dns_names", [])):
            internal = d.get("internal", {}) or {}
            external = d.get("external", {}) or {}
            targets = d.get("targets", {}) or {}
            cf = d.get("cloudflare", None)
            cf_obj = None
            if isinstance(cf, dict):
                cf_obj = CloudflareMeta(
                    target_ip=cf.get("target_ip"),
                    proxy_status=cf.get("proxy_status"),
                )
            dn = DNSName(
                dns_id=str(d["dns_id"]),
                kind=str(d.get("kind", "")),
                fqdn=_strip_dot(str(d["fqdn"])),
                targets=DNSTargets(
                    service_id=targets.get("service_id"),
                    asset_id=targets.get("asset_id"),
                ),
                internal=DNSInternal(
                    enabled=bool(internal.get("enabled", False)),
                    provider=str(internal.get("provider", "")),
                    address=str(internal.get("address", "")),
                    record_type=str(internal.get("record_type", "")),
                    publish_scopes=list(internal.get("publish_scopes", []) or []),
                    interface_id=internal.get("interface_id"),
                    target=internal.get("target"),
                ),
                external=DNSExternal(
                    enabled=bool(external.get("enabled", False)),
                    provider=external.get("provider"),
                    record_type=external.get("record_type"),
                    target=external.get("target"),
                ),
                cloudflare=cf_obj,
            )
            dns_names[dn.dns_id] = dn

    g = vdoc.get("globals", {}) or {}
    caddy_cfg = None
    if isinstance(g.get("caddy"), dict):
        c = g["caddy"]
        caddy_cfg = CaddyConfig(
            ssh_host=str(c.get("ssh_host", "")).strip(),
            ssh_user=str(c.get("ssh_user", "")).strip(),
            ssh_port=int(c.get("ssh_port", 22)),
            use_sudo=bool(c.get("use_sudo", False)),
            caddyfile_path=str(c.get("caddyfile_path", "/etc/caddy/Caddyfile")).strip(),
            compose_dir=str(c.get("compose_dir", "/etc/caddy")).strip(),
        )
    
    glb = Globals(
        base_domain=str(g.get("base_domain", "")).strip(),
        user_vlan=str(g.get("user_vlan", "")).strip(),
        access_publish_to_user_vlan=bool(g.get("access_publish_to_user_vlan", False)),
        caddy_ip=str(g.get("caddy_ip", "")).strip(),
        caddy=caddy_cfg,
    )


    return SOT(globals=glb, vlans=vlans, assets=assets, services=services, dns_names=dns_names)


def resolve_asset_interface_ip(asset: Asset, interface_id: str) -> str:
    for itf in asset.interfaces:
        if itf.if_id == interface_id:
            if itf.ip == "dynamic":
                raise ValueError(f"Interface {asset.asset_id}:{interface_id} has dynamic IP; cannot use for DNS A record")
            return itf.ip
    raise KeyError(f"Asset {asset.asset_id} has no interface {interface_id}")


def owner_vlan_for_dns(dn: DNSName, services: dict[str, Service], assets: dict[str, Asset]) -> str:
    if dn.targets.service_id:
        return services[dn.targets.service_id].vlan_id
    if dn.targets.asset_id:
        # Prefer explicit internal.interface_id if present
        iface = dn.internal.interface_id
        if not iface:
            a = assets[dn.targets.asset_id]
            if len(a.interfaces) == 1:
                return a.interfaces[0].vlan_id
            raise ValueError(f"{dn.dns_id}: asset target requires internal.interface_id when asset has multiple interfaces")
        a = assets[dn.targets.asset_id]
        for itf in a.interfaces:
            if itf.if_id == iface:
                return itf.vlan_id
        raise ValueError(f"{dn.dns_id}: asset {a.asset_id} missing interface {iface}")
    raise ValueError(f"{dn.dns_id}: must target either service_id or asset_id")


def publish_vlans_for_dns(dn: DNSName, sot: SOT) -> list[str]:
    owner = owner_vlan_for_dns(dn, sot.services, sot.assets)
    out: list[str] = []
    for scope in dn.internal.publish_scopes:
        if scope == "self":
            out.append(owner)
        elif scope == "user_vlan_if_enabled":
            if sot.globals.access_publish_to_user_vlan and sot.globals.user_vlan:
                out.append(sot.globals.user_vlan)
    # de-dupe preserve order
    seen = set()
    uniq = []
    for v in out:
        if v not in seen:
            uniq.append(v)
            seen.add(v)
    return uniq


def resolve_internal_a_ip(dn: DNSName, sot: SOT) -> str:
    # Allowed values: routing_internal_dns_target, asset_interface_ip
    if dn.internal.address == "routing_internal_dns_target":
        if not dn.targets.service_id:
            raise ValueError(f"{dn.dns_id}: routing_internal_dns_target requires targets.service_id")
        svc = sot.services[dn.targets.service_id]
        if not svc.routing.internal_dns_target:
            raise ValueError(f"{dn.dns_id}: service {svc.service_id} missing routing.internal_dns_target")
        return svc.routing.internal_dns_target

    if dn.internal.address == "asset_interface_ip":
        if dn.targets.service_id:
            svc = sot.services[dn.targets.service_id]
            a = sot.assets[svc.asset_id]
            return resolve_asset_interface_ip(a, svc.interface_id)
        if dn.targets.asset_id:
            a = sot.assets[dn.targets.asset_id]
            if not dn.internal.interface_id:
                raise ValueError(f"{dn.dns_id}: asset_interface_ip requires internal.interface_id for asset targets")
            return resolve_asset_interface_ip(a, dn.internal.interface_id)

    raise ValueError(f"{dn.dns_id}: unsupported internal.address for A record: {dn.internal.address}")


def resolve_internal_cname_target(dn: DNSName) -> str:
    # Your guidance: CNAME records carry their target explicitly; if internal.target exists, use it.
    if dn.internal.target:
        return _strip_dot(dn.internal.target)
    # Fallback: treat 'address' as target if it isn't one of the known A-address selectors.
    if dn.internal.address not in ("routing_internal_dns_target", "asset_interface_ip"):
        return _strip_dot(dn.internal.address)
    raise ValueError(f"{dn.dns_id}: CNAME missing internal.target (or equivalent)")


def build_pihole_records_by_vlan(sot: SOT) -> dict[str, dict[str, list[str]]]:
    """
    Returns:
      {
        vlan_id: { "hosts": ["IP FQDN", ...], "cnames": ["cname,target", ...] }
      }
    Only includes records that should land on pihole-served VLANs.
    Respects include_access_fqdn for 'access' records on the target VLAN.
    """
    out: dict[str, dict[str, list[str]]] = {}

    for dn in sot.dns_names.values():
        if not dn.internal.enabled:
            continue

        publish_vlans = publish_vlans_for_dns(dn, sot)
        for vlan_id in publish_vlans:
            vlan = sot.vlans.get(vlan_id)
            if not vlan:
                continue
            if vlan.dns.default_provider != "pihole":
                continue
            if dn.kind == "access" and not vlan.dns.include_access_fqdn:
                continue

            bucket = out.setdefault(vlan_id, {"hosts": [], "cnames": []})
            rtype = dn.internal.record_type.upper()
            if rtype == "A":
                ip = resolve_internal_a_ip(dn, sot)
                bucket["hosts"].append(f"{ip} {dn.fqdn}")
            elif rtype == "CNAME":
                target = resolve_internal_cname_target(dn)
                bucket["cnames"].append(f"{dn.fqdn},{target}")
            else:
                raise ValueError(f"{dn.dns_id}: unsupported internal.record_type: {dn.internal.record_type}")

    # deterministic ordering + de-dupe
    for vlan_id, bucket in out.items():
        for k in ("hosts", "cnames"):
            uniq = sorted(set(bucket[k]))
            bucket[k] = uniq
    return out

