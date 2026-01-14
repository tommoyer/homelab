#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any, DefaultDict

import yaml

KIND_KEYS = ["vlans", "assets", "services", "dns_names"]

KIND_TO_PURPOSE = {
    "vlans": (
        "Defines VLANs and global DNS/routing defaults used to derive other configuration "
        "(assets, services, DNS names)."
    ),
    "assets": (
        "Defines one or more assets (devices/hosts) and their network interfaces. "
        "These are referenced by `services` and `dns_names`."
    ),
    "services": (
        "Defines one or more network services running on assets, including ports and routing "
        "behavior (e.g., via Caddy)."
    ),
    "dns_names": (
        "Defines one or more DNS names/records to publish internally and/or externally, "
        "targeting either an asset or a service."
    ),
}

KIND_TO_ID_FIELD = {
    "vlans": "vlan_id",
    "assets": "asset_id",
    "services": "service_id",
    "dns_names": "dns_id",
}


@dataclass
class FieldStat:
    examples: list[str]
    types: set[str] = dc_field(default_factory=set)

    def add_example(self, example: str, max_examples: int = 6) -> None:
        if example in self.examples:
            return
        if len(self.examples) >= max_examples:
            return
        self.examples.append(example)


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "list"
    return type(value).__name__


# Best-effort descriptions for observed fields.
# These are used both in docs/schema.md and per-file pages.
FIELD_DESCRIPTIONS: dict[str, str] = {
    "schema_version": "Schema version for this YAML document.",
    "globals": "Global defaults used when generating/deriving other config (DNS names, access publishing, etc.).",
    "globals.base_domain": "Base public DNS zone / domain.",
    "globals.user_vlan": "VLAN id treated as the user-facing VLAN (used by publishing rules).",
    "globals.access_publish_to_user_vlan": (
        "If true, access FQDNs may also be published into the user VLAN, depending on per-record "
        "publish scopes."
    ),
    "globals.caddy_ip": (
        "IP address of the Caddy reverse proxy (used as an internal DNS target for services routed "
        "via Caddy)."
    ),
    "vlans": "List of VLAN definitions.",
    "vlans[]": "One VLAN definition object within the `vlans` list.",
    "vlans[].vlan_id": "Stable identifier for the VLAN used throughout the repo.",
    "vlans[].vlan_tag": "802.1Q VLAN tag number.",
    "vlans[].cidr": "IPv4 CIDR for the VLAN (or null if not managed here).",
    "vlans[].dns": "DNS behavior for this VLAN.",
    "vlans[].dns.default_provider": "Default DNS provider for records in this VLAN (e.g., pihole, mikrotik).",
    "vlans[].dns.include_access_fqdn": "If true, include access FQDNs in this VLAN’s DNS namespace.",
    "vlans[].suffixes": "DNS suffixes used to construct FQDNs.",
    "vlans[].suffixes.infra": "Suffix/zone for internal infrastructure names for this VLAN.",
    "vlans[].suffixes.access": "Suffix/zone for user-facing/access names.",
    "vlans[].servers": "Connection details for managing infra services in this VLAN (e.g., Pi-hole host).",
    "vlans[].servers.dns_host": "Host/IP used to manage the DNS server for this VLAN.",
    "vlans[].servers.dns_type": "DNS server type/implementation.",
    "vlans[].servers.ssh_user": "SSH username used for remote management.",
    "vlans[].servers.ssh_port": "SSH port.",
    "vlans[].servers.use_sudo": "Whether management commands should be run with sudo.",
    "assets": "List of assets (devices/hosts/things) on the network.",
    "assets[]": "One asset definition object within the `assets` list.",
    "assets[].asset_id": "Stable identifier for the asset; used by services and DNS names.",
    "assets[].hostname": "Hostname for the asset.",
    "assets[].type": "Asset type (best-effort; often 'unknown').",
    "assets[].interfaces": "Network interfaces for the asset.",
    "assets[].interfaces[]": "One interface definition object within an asset’s `interfaces` list.",
    "assets[].interfaces[].if_id": "Stable interface identifier within the asset.",
    "assets[].interfaces[].vlan_id": "VLAN where this interface lives.",
    "assets[].interfaces[].ip": "IP address for the interface or 'dynamic' if DHCP/reserved elsewhere.",
    "assets[].interfaces[].dns_provider": (
        "DNS provider for publishing this interface’s records (or where the VLAN inherits provider "
        "behavior)."
    ),
    "services": "List of services (network endpoints) running on assets.",
    "services[]": "One service definition object within the `services` list.",
    "services[].service_id": "Stable identifier for the service; often includes port/protocol.",
    "services[].name": "Human-friendly service name.",
    "services[].asset_id": "Asset where this service runs.",
    "services[].vlan_id": "VLAN where the service is considered to live.",
    "services[].interface_id": "Which interface on the asset should be used for backend addressing.",
    "services[].ports": "Port definitions for the service.",
    "services[].ports.service_ports": "Ports the service listens on (authoritative).",
    "services[].ports.service_ports[]": "One `service_port` entry (port/protocol tuple).",
    "services[].ports.service_ports[].port": "TCP/UDP port.",
    "services[].ports.service_ports[].proto": "Transport protocol.",
    "services[].ports.firewall_ports": (
        "Ports that should be exposed via firewall/reverse proxy (commonly 80/443 when using Caddy)."
    ),
    "services[].ports.firewall_ports[]": "One `firewall_port` entry (port/protocol tuple).",
    "services[].ports.firewall_ports[].port": "Firewall-exposed port.",
    "services[].ports.firewall_ports[].proto": "Firewall-exposed protocol.",
    "services[].routing": "How clients should reach the service.",
    "services[].routing.via_caddy": (
        "If true, service is routed via Caddy; DNS access names typically point at internal_dns_target."
    ),
    "services[].routing.internal_dns_target": (
        "When routing via Caddy, the internal A record target (often Caddy’s IP)."
    ),
    "services[].backend": "Backend connection details.",
    "services[].backend.ip": "Override backend IP (null means derive from asset interface).",
    "services[].backend.port": "Backend port clients should connect to (often matches service_ports[].port).",
    "dns_names": "List of DNS names to publish.",
    "dns_names[]": "One DNS name/record definition object within the `dns_names` list.",
    "dns_names[].dns_id": "Stable identifier for the DNS record object.",
    "dns_names[].kind": "Record kind: infra (internal naming) or access (user-facing name).",
    "dns_names[].fqdn": "Fully qualified domain name to publish.",
    "dns_names[].targets": "What this DNS name points to: either an asset or a service.",
    "dns_names[].targets.service_id": "Service target (mutually exclusive with asset_id).",
    "dns_names[].targets.asset_id": "Asset target (mutually exclusive with service_id).",
    "dns_names[].internal": "Internal DNS publication config (e.g., to Pi-hole).",
    "dns_names[].internal.enabled": "Whether to publish this record internally.",
    "dns_names[].internal.provider": (
        "Internal DNS provider selection; inherit_vlan means use the VLAN’s configured/default provider."
    ),
    "dns_names[].internal.address": "How to compute the record target address.",
    "dns_names[].internal.record_type": "DNS record type (observed: A).",
    "dns_names[].internal.interface_id": "When targeting an asset interface, which interface to use.",
    "dns_names[].internal.publish_scopes": "Where to publish this internal record.",
    "dns_names[].internal.publish_scopes[]": "Publish scope entry.",
    "dns_names[].external": "External/public DNS publication config.",
    "dns_names[].external.enabled": "Whether to publish this record externally.",
}

FIELD_NOTES: dict[str, str] = {
    "dns_names[].internal.publish_scopes[]": (
        "Best-effort: 'self' means the record is published within its own VLAN; "
        "'user_vlan_if_enabled' publishes into the user VLAN if enabled globally."
    ),
    "services[].routing.internal_dns_target": "Only present when via_caddy=true in observed files.",
    "dns_names[].internal.interface_id": "Only present when address=asset_interface_ip in observed files.",
}


def _as_example(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        s = value.strip()
        if len(s) > 80:
            s = s[:77] + "..."
        return s
    if isinstance(value, dict):
        return f"object(keys={len(value)})"
    if isinstance(value, list):
        return f"list(len={len(value)})"
    s = str(value)
    if len(s) > 80:
        s = s[:77] + "..."
    return s


def _infer_kind(doc: Any) -> str:
    if isinstance(doc, dict):
        for key in KIND_KEYS:
            if key in doc:
                return key
    return "unknown"


def _extract_objects(doc: Any, kind: str) -> list[dict[str, Any]]:
    if not isinstance(doc, dict):
        return []
    value = doc.get(kind)
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    return []


def _object_ids(objects: list[dict[str, Any]], kind: str) -> list[str]:
    id_field = KIND_TO_ID_FIELD.get(kind)
    ids: list[str] = []
    for idx, obj in enumerate(objects):
        if id_field and id_field in obj and obj[id_field] is not None:
            ids.append(str(obj[id_field]))
        else:
            ids.append(str(idx))
    return ids


def _walk_fields(value: Any, path: str, stats: DefaultDict[str, FieldStat]) -> None:
    stats[path].add_example(_as_example(value))
    stats[path].types.add(_value_type(value))

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            _walk_fields(child, child_path, stats)
        return

    if isinstance(value, list):
        item_path = f"{path}[]" if path else "[]"
        stats[item_path].add_example(_as_example(value))
        stats[item_path].types.add("list_item")
        for item in value:
            _walk_fields(item, item_path, stats)


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _doc_field_row(
    field: str,
    examples: list[str],
    types: set[str],
    required_repo: str,
    required_file: str,
) -> tuple[str, str, str, str, str, str, str]:
    ex = ", ".join(f"`{_md_escape(e)}`" for e in examples if e != "")
    # Use comma-separated values to avoid breaking Markdown tables.
    ty = ", ".join(f"`{t}`" for t in sorted(types)) if types else ""
    desc = FIELD_DESCRIPTIONS.get(field)
    notes = FIELD_NOTES.get(field, "")
    if not desc:
        desc = "Undocumented field (observed in repo)."
    return field, ty, required_repo, required_file, ex, desc, notes


def _generate_file_doc(
    rel_path: str,
    doc: Any,
    kind_requiredness: dict[str, dict[str, bool]],
) -> str:
    kind = _infer_kind(doc)
    objects = _extract_objects(doc, kind)
    object_ids = _object_ids(objects, kind)
    schema_version = None
    if isinstance(doc, dict):
        schema_version = doc.get("schema_version")

    stats: DefaultDict[str, FieldStat] = DefaultDict(lambda: FieldStat(examples=[]))
    if doc is None:
        pass
    else:
        _walk_fields(doc, "", stats)

    # Remove empty root entry "" from field listing; it's not useful.
    if "" in stats:
        del stats[""]

    required_repo_map = kind_requiredness.get(kind, {})

    # Per-file requiredness: within this file, for this kind, which object-field paths
    # appear in *all* objects.
    required_file_map: dict[str, bool] = {}
    if kind in KIND_KEYS and objects:
        file_total = len(objects)
        file_field_counts: DefaultDict[str, int] = DefaultDict(int)
        for obj in objects:
            obj_stats: DefaultDict[str, FieldStat] = DefaultDict(lambda: FieldStat(examples=[]))
            _walk_fields(obj, f"{kind}[]", obj_stats)
            if "" in obj_stats:
                del obj_stats[""]
            for field_path in obj_stats.keys():
                file_field_counts[field_path] += 1
        required_file_map = {field_path: count == file_total for field_path, count in file_field_counts.items()}

    rows = []
    for field_path in sorted(stats.keys()):
        if field_path in required_repo_map:
            required_repo = "yes" if required_repo_map[field_path] else "no"
        else:
            required_repo = "n/a"

        if field_path in required_file_map:
            required_file = "yes" if required_file_map[field_path] else "no"
        else:
            required_file = "n/a"

        rows.append(
            _doc_field_row(
                field_path,
                stats[field_path].examples,
                stats[field_path].types,
                required_repo,
                required_file,
            )
        )

    purpose = KIND_TO_PURPOSE.get(kind, "Documents the contents of this YAML file.")

    lines: list[str] = []
    lines.append(f"# {rel_path}\n")
    lines.append("## Purpose\n")
    lines.append(f"{purpose}\n")

    lines.append("## Contents\n")
    if schema_version is not None:
        lines.append(f"- schema_version: `{schema_version}`\n")
    lines.append(f"- kind: `{kind}`\n")
    lines.append(f"- object_count: `{len(objects)}`\n")

    lines.append("\n## Objects\n")
    if object_ids:
        for oid in object_ids:
            lines.append(f"- `{_md_escape(oid)}`\n")
    else:
        lines.append("- *(none detected)*\n")

    lines.append("\n## Field Documentation\n")
    lines.append(
        "This section documents every field path observed in this file. "
        "Field meanings are best-effort and derived from usage across the repository.\n\n"
    )
    lines.append("| Field | Type | Required (repo)? | Required (file)? | Examples | Description | Notes |\n")
    lines.append("|---|---|---|---|---|---|---|\n")
    for field_path, ty, required_repo, required_file, examples, desc, notes in rows:
        lines.append(
            f"| `{_md_escape(field_path)}` | {ty} | `{required_repo}` | `{required_file}` | {examples} | "
            f"{_md_escape(desc)} | {_md_escape(notes)} |\n"
        )

    # Link to schema reference (relative depth differs by directory)
    depth = len(Path(rel_path).parts) - 1
    schema_rel = "../" * depth + "schema.md"
    lines.append("\n\n## Related\n\n")
    lines.append(f"- Schema reference: [{schema_rel}]({schema_rel})\n")

    return "".join(lines)


def _generate_schema_doc(
    schema_rows: list[tuple[str, FieldStat]],
    required_any_kind: dict[str, str],
) -> str:
    lines: list[str] = []
    lines.append("# Schema Reference\n\n")
    lines.append("This is a best-effort reference for fields observed in this repository.\n\n")
    lines.append("## Notes\n\n")
    lines.append("- Most files use `schema_version: 1`.\n\n")
    lines.append("- Lists are documented using `[]` in field paths (e.g., `assets[]`, `assets[].interfaces[]`).\n\n")
    lines.append(
        "- If a field appears in a file but is not documented here, the per-file doc will label it "
        "as 'Undocumented field (observed in repo)'.\n\n"
    )

    lines.append("\n## Fields\n\n")
    lines.append("| Field | Type | Required? | Examples | Description | Notes |\n")
    lines.append("|---|---|---|---|---|---|\n")

    for field_path, stat in schema_rows:
        required = required_any_kind.get(field_path, "n/a")
        _, ty, required, _, examples, desc, notes = _doc_field_row(
            field_path,
            stat.examples,
            stat.types,
            required,
            "n/a",
        )
        lines.append(
            f"| `{_md_escape(field_path)}` | {ty} | `{required}` | {examples} | "
            f"{_md_escape(desc)} | {_md_escape(notes)} |\n"
        )

    return "".join(lines)


def _generate_readme_doc() -> str:
    return (
        "# Network Config YAML (data/)\n\n"
        "This folder contains declarative network inventory and naming configuration. Files are grouped by intent:\n\n"
        "- `vlans.yaml`: VLAN definitions and global defaults\n\n"
        "- `assets/`: device/host inventory (one file per asset today, but can be many)\n\n"
        "- `services/`: services/endpoints running on assets (one file per service today, but can be many)\n\n"
        "- `dns-names/`: DNS records to publish (one file per record today, but can be many)\n\n"
        "\n## How things link together\n\n"
        "- An `asset_id` identifies a device/host.\n\n"
        "- A `service_id` identifies a network service running on an asset (`services[].asset_id`).\n\n"
        "- A `dns_id` identifies a DNS record which targets either a `service_id` or an `asset_id`.\n\n"
        "- `vlan_id` values tie assets/services/records back to a VLAN definition in `vlans.yaml`.\n\n"
        "\n## Generated documentation\n\n"
        "- Index of all YAML file docs: [index.md](index.md)\n\n"
        "- Schema reference: [schema.md](schema.md)\n\n"
    )


def _iter_yaml_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.yaml"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        # Exclude generated docs and venv
        if rel.parts and rel.parts[0] in {"docs", ".venv"}:
            continue
        files.append(path)
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Markdown docs for YAML network config files.")
    parser.add_argument("--root", default=".", help="Root directory containing YAML files (default: .)")
    parser.add_argument("--out", default="docs", help="Output docs directory (default: docs)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_dir = (root / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out).resolve()

    yaml_files = _iter_yaml_files(root)

    # First pass: parse YAML and collect schema + requiredness across repo
    schema_stats: DefaultDict[str, FieldStat] = DefaultDict(lambda: FieldStat(examples=[]))
    kind_total_objects: dict[str, int] = {k: 0 for k in KIND_KEYS}
    kind_field_counts: dict[str, DefaultDict[str, int]] = {k: DefaultDict(int) for k in KIND_KEYS}

    parsed_docs: list[tuple[str, Any]] = []
    file_rel_paths: list[str] = []

    # Doc-level requiredness across all YAML documents
    total_yaml_docs = 0
    schema_version_present = 0

    for yaml_path in yaml_files:
        rel = str(yaml_path.relative_to(root)).replace("\\", "/")
        file_rel_paths.append(rel)
        try:
            doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            parsed_docs.append((rel, {"_parse_error": str(e)}))
            continue

        parsed_docs.append((rel, doc))

        if isinstance(doc, dict):
            total_yaml_docs += 1
            if "schema_version" in doc:
                schema_version_present += 1

        if doc is not None:
            _walk_fields(doc, "", schema_stats)
            if "" in schema_stats:
                del schema_stats[""]

        kind = _infer_kind(doc)
        if kind in KIND_KEYS:
            objects = _extract_objects(doc, kind)
            kind_total_objects[kind] += len(objects)
            for obj in objects:
                obj_stats: DefaultDict[str, FieldStat] = DefaultDict(lambda: FieldStat(examples=[]))
                _walk_fields(obj, f"{kind}[]", obj_stats)
                if "" in obj_stats:
                    del obj_stats[""]
                for field_path in obj_stats.keys():
                    kind_field_counts[kind][field_path] += 1

    # Determine requiredness per kind: field appears in all objects of that kind across the repo
    kind_requiredness: dict[str, dict[str, bool]] = {}
    for kind in KIND_KEYS:
        total = kind_total_objects.get(kind, 0)
        required_map: dict[str, bool] = {}
        if total > 0:
            for field_path, count in kind_field_counts[kind].items():
                required_map[field_path] = count == total
        kind_requiredness[kind] = required_map

    # For schema.md (kind-agnostic view), mark a field as required if it is required in any kind
    required_any_kind: dict[str, str] = {}
    for kind, required_map in kind_requiredness.items():
        for field_path, is_required in required_map.items():
            if is_required:
                required_any_kind[field_path] = "yes"
            elif field_path not in required_any_kind:
                # only set to "no" if we've seen it in some kind; otherwise leave unset
                required_any_kind[field_path] = "no"

    # Also treat schema_version as required if it is present in all parsed YAML documents.
    if total_yaml_docs > 0:
        required_any_kind["schema_version"] = "yes" if schema_version_present == total_yaml_docs else "no"

    # Second pass: generate per-file docs (now that requiredness is known)
    for rel, doc in parsed_docs:
        if isinstance(doc, dict) and "_parse_error" in doc:
            content = f"# {rel}\n\n## Error\n\nFailed to parse YAML: `{doc['_parse_error']}`\n"
            _write_text(out_dir / "files" / f"{rel}.md", content)
            continue

        file_doc = _generate_file_doc(rel, doc, kind_requiredness)
        _write_text(out_dir / "files" / f"{rel}.md", file_doc)

    # docs/index.md
    index_lines: list[str] = []
    index_lines.append("# YAML File Index\n\n")
    index_lines.append("All YAML files documented below. Each YAML file may contain multiple objects.\n\n")
    for rel in file_rel_paths:
        index_lines.append(f"- [{rel}](files/{rel}.md)\n")
    _write_text(out_dir / "index.md", "".join(index_lines))

    # docs/schema.md
    schema_rows = [(field, schema_stats[field]) for field in sorted(schema_stats.keys())]
    _write_text(out_dir / "schema.md", _generate_schema_doc(schema_rows, required_any_kind))

    # docs/README.md
    _write_text(out_dir / "README.md", _generate_readme_doc())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
