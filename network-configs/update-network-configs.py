#!/usr/bin/env python3
"""
update-network-configs.py

Usage:
  python update-network-configs.py --inventory "System Inventory - Nodes.csv" --caddy-ip 192.168.20.3 [--dry-run]

Dependencies:
  - Python 3.11+ (standard library) OR `pip install tomli`
  - dnscontrol (installed and in PATH)
  - ssh / scp (installed and in PATH)
  - Environment Var: CLOUDFLARE_API_TOKEN (required for Cloudflare updates)
"""

import argparse
import csv
import datetime
import getpass
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# --- Dependency Check: Python Libraries ---
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("\n[!] CRITICAL ERROR: Missing Python dependency 'tomli'", file=sys.stderr)
        print("    This script requires a TOML parser.", file=sys.stderr)
        print("    Please run: pip install tomli", file=sys.stderr)
        sys.exit(1)


# --- Dependency Check: System Tools ---
def load_config(config_path: str) -> Dict[str, Any]:
    if not os.path.isfile(config_path):
        return {}
    try:
        with open(config_path, 'rb') as f:
            return tomllib.load(f)
    except Exception as e:
        print(f"Error reading config {config_path}: {e}", file=sys.stderr)
        sys.exit(1)

def check_prerequisites(needs_dnscontrol: bool = True) -> bool:
    """
    Verifies that all required system tools are installed and accessible.
    """
    missing_tools = []
    
    # 1. Check Core Tools (SSH/SCP)
    if not shutil.which("ssh"):
        missing_tools.append("ssh")
    if not shutil.which("scp"):
        missing_tools.append("scp")

    # 2. Check DNSControl
    if needs_dnscontrol and not shutil.which("dnscontrol"):
        missing_tools.append("dnscontrol")

    if not missing_tools:
        return True

    # Generate Helpful Error Messages
    print("\n[!] CRITICAL ERROR: Missing required system tools.", file=sys.stderr)
    print(f"    Missing: {', '.join(missing_tools)}", file=sys.stderr)
    
    system = platform.system().lower()
    
    if "dnscontrol" in missing_tools:
        print("\n--- How to install DNSControl ---")
        if system == "darwin": # macOS
            print("    brew install dnscontrol")
        elif system == "linux":
            print("    (Debian/Ubuntu):")
            print("    curl -sL https://github.com/StackExchange/dnscontrol/releases/download/v4.8.2/dnscontrol-4.8.2.linux_amd64.deb -o dnscontrol.deb")
            print("    sudo dpkg -i dnscontrol.deb")
        else:
            print("    Visit: https://docs.dnscontrol.org/getting-started/installation")

    if "ssh" in missing_tools or "scp" in missing_tools:
        print("\n--- How to install SSH/SCP ---")
        if system == "windows":
            print("    Install Git for Windows (includes Git Bash) or enable OpenSSH Client in Windows Features.")
        else:
            print("    sudo apt install openssh-client  # Ubuntu/Debian")
            print("    sudo yum install openssh-clients # RHEL/CentOS")

    if not shutil.which("sshpass"):
        print("\n[Info] 'sshpass' is not installed. Install it to avoid multiple password prompts for Mikrotik updates.", file=sys.stderr)
        if system == "darwin":
            print("    brew install sshpass")
        elif system == "linux":
            print("    sudo apt install sshpass")

    return False


def fetch_inventory_csv(path_or_url: str) -> Tuple[str, bool]:
    """
    Checks if the input is a URL or a local path.
    If URL (Google Sheet), downloads to a temp file.
    Returns (file_path, is_temporary).
    """
    # Check if it looks like a URL
    if not (path_or_url.startswith("http://") or path_or_url.startswith("https://")):
        return path_or_url, False

    # It is a URL, assume Google Sheet for now
    sheet_url = path_or_url
    
    # Extract Sheet ID
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
    if not match:
        print(f"[!] Error: Could not extract Spreadsheet ID from URL: {sheet_url}", file=sys.stderr)
        sys.exit(1)
    
    sheet_id = match.group(1)
    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    
    print("Downloading inventory from Google Sheets...")
    
    try:
        # Create a temp file
        fd, temp_path = tempfile.mkstemp(suffix='.csv', prefix='inventory-')
        os.close(fd) # Close the file descriptor, we'll open it normally later if needed or just pass path
        
        with urllib.request.urlopen(export_url) as response:
            if response.status != 200:
                print(f"[!] Error: HTTP {response.status} downloading CSV.", file=sys.stderr)
                os.unlink(temp_path)
                sys.exit(1)
            
            with open(temp_path, 'wb') as f:
                f.write(response.read())
        
        print(f"Downloaded to temporary file: {temp_path}")
        return temp_path, True

    except urllib.error.URLError as e:
        print(f"[!] Error downloading CSV: {e}", file=sys.stderr)
        sys.exit(1)


def parse_inventory_csv(path: str, servers_config: Dict[str, Any] = {}, user_vlan: Optional[str] = None, caddy_ip: Optional[str] = None) -> Tuple[Dict[str, Dict[str, List[Dict[str, Any]]]], List[Dict[str, Any]], List[Dict[str, str]]]:
    """
    Reads the inventory CSV and returns three datasets:
    1. Internal Groups: vlan_key -> {'pihole': [], 'mikrotik': []}
    2. Cloudflare Records: List of dicts for DNSControl
    3. Caddy Records: List of dicts for Caddyfile map
    """
    groups: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    cf_records: List[Dict[str, Any]] = []
    caddy_records: List[Dict[str, str]] = []

    try:
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            # Normalize headers
            reader.fieldnames = [name.strip() for name in reader.fieldnames] if reader.fieldnames else []

            for row in reader:
                # --- Read Columns ---
                node_name = row.get('Node', '').strip()
                lan_ip = row.get('LAN IP', '').strip()
                vlan_raw = row.get('VLAN', '').strip()
                subdomain = row.get('Subdomain', '').strip()
                
                access_fqdn = row.get('Access FQDN', '').strip()
                infra_fqdn = row.get('Infrastructure FQDN', '').strip()
                internal_target = row.get('Internal DNS Target', '').strip()
                
                cf_enabled = row.get('Cloudflare Enabled', '').strip().lower()
                cf_target = row.get('Cloudflare Target IP', '').strip()
                proxy_status = row.get('Proxy Status', '').strip().lower()
                
                # New Column for Ports
                service_ports = row.get('Service Ports', '').strip()
                firewall_ports = row.get('Firewall ports') or row.get('Firewall Ports') or ''
                firewall_ports = firewall_ports.strip()
                
                dns_provider = row.get('DNS Provider', 'pihole').strip().lower()

                # --- 1. Cloudflare Processing ---
                if cf_enabled in ('true', 'yes', '1', 'on'):
                    cf_name = access_fqdn if access_fqdn else infra_fqdn
                    
                    if cf_name and cf_target:
                        # Naive domain extraction (SLD.TLD)
                        domain = ".".join(cf_name.split('.')[-2:])

                        cf_records.append({
                            'name': cf_name,
                            'target': cf_target,
                            'proxied': proxy_status in ('proxied', 'on', 'true', 'yes'),
                            'domain': domain
                        })

                # --- 2. Internal Processing (Pi-hole / Mikrotik) ---
                vlan_key = (subdomain if subdomain else vlan_raw).lower()
                
                # Validation
                if not lan_ip or lan_ip.lower() == 'dynamic' or not infra_fqdn or not vlan_key:
                    continue

                if dns_provider not in ('pihole', 'mikrotik'):
                    dns_provider = 'pihole'

                groups.setdefault(vlan_key, {'pihole': [], 'mikrotik': [], 'nat': []})
                
                # Record 1: Infrastructure
                groups[vlan_key][dns_provider].append({
                    'ip': lan_ip,
                    'fqdn': infra_fqdn,
                    'comment': f"Infra: {node_name}",
                    'ports': service_ports 
                })

                # NAT Processing
                if firewall_ports and internal_target:
                    groups[vlan_key]['nat'].append({
                        'ip': internal_target,
                        'ports': firewall_ports,
                        'comment': f"NAT: {node_name}"
                    })

                # Check if Access FQDN should be included for this VLAN
                # Default to False if not specified
                vlan_config = servers_config.get(vlan_key, {})
                include_access = vlan_config.get('include_access_fqdn', False)

                # Record 2: Access
                if access_fqdn and include_access:
                    final_ip = internal_target if internal_target else lan_ip
                    groups[vlan_key][dns_provider].append({
                        'ip': final_ip,
                        'fqdn': access_fqdn,
                        'comment': f"Access: {node_name}",
                        'ports': service_ports 
                    })

                # --- 3. User VLAN Cross-Mapping ---
                if user_vlan and internal_target and access_fqdn:
                    user_vlan_key = user_vlan.lower()
                    
                    # Determine provider for the user VLAN
                    user_vlan_conf = servers_config.get(user_vlan_key, {})
                    target_provider = user_vlan_conf.get('type', 'pihole')
                    
                    # Avoid duplicates if we already added it in Record 2
                    # This happens if the current row IS the user VLAN, and include_access is True,
                    # AND the provider matches.
                    already_added = (vlan_key == user_vlan_key and include_access and dns_provider == target_provider)
                    
                    if not already_added:
                        groups.setdefault(user_vlan_key, {'pihole': [], 'mikrotik': [], 'nat': []})
                        groups[user_vlan_key][target_provider].append({
                            'ip': internal_target,
                            'fqdn': access_fqdn,
                            'comment': f"User Access: {node_name}",
                            'ports': service_ports 
                        })

                # --- 4. Caddy Processing ---
                if caddy_ip and internal_target == caddy_ip and access_fqdn and lan_ip:
                     backend_port = ""
                     if service_ports:
                         # Take the first port
                         first_port = service_ports.split(',')[0].strip()
                         if '/' in first_port:
                             first_port = first_port.split('/')[0].strip()
                         backend_port = f":{first_port}"
                     
                     caddy_records.append({
                         'host': access_fqdn,
                         'backend': f"{lan_ip}{backend_port}"
                     })

    except FileNotFoundError:
        print(f"[!] Error: Inventory file not found: {path}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"[!] Error reading {path}: {e}", file=sys.stderr)
        sys.exit(2)

    return groups, cf_records, caddy_records


# --- DNSControl Helper Functions ---

def process_dnscontrol(records: List[Dict[str, Any]], args: argparse.Namespace) -> None:
    """Writes records to JSON and runs DNSControl Preview/Push."""
    if not records:
        print("\n--- DNSControl: No Cloudflare records found in CSV. Skipping. ---")
        return

    if "CLOUDFLARE_API_TOKEN" not in os.environ and not args.dry_run:
        print("\n[!] ERROR: CLOUDFLARE_API_TOKEN environment variable is missing.", file=sys.stderr)
        print("    DNSControl requires this token to authenticate with Cloudflare.", file=sys.stderr)
        return

    json_filename = "external_records.json"
    
    print(f"\n--- DNSControl: Processing {len(records)} external records ---")
    
    # In dry-run, save a copy to dry-run/ folder for inspection
    if args.dry_run:
        dry_run_json = os.path.join("dry-run", json_filename)
        try:
            with open(dry_run_json, 'w', encoding='utf-8') as f:
                json.dump(records, f, indent=4)
            print(f"  [Dry Run] Generated local file: {dry_run_json}")
        except IOError as e:
            print(f"Error writing {dry_run_json}: {e}", file=sys.stderr)

    try:
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(records, f, indent=4)
        print(f"Generated {json_filename}")
    except IOError as e:
        print(f"Error writing {json_filename}: {e}", file=sys.stderr)
        return

    print("Running DNSControl Preview...")
    try:
        subprocess.run(["dnscontrol", "preview"], check=False) 
    except FileNotFoundError:
        print("Error: 'dnscontrol' command not found.", file=sys.stderr)

    if args.dry_run:
        print("Dry-run enabled: Skipping push.")
        if not args.keep and os.path.exists(json_filename):
            os.remove(json_filename)
            print(f"Cleaned up {json_filename}")
        return

    print(f"\n--- Content of {json_filename} ---")
    print(json.dumps(records, indent=4))
    print("-----------------------------------\n")

    confirm = input("\nDo these changes look correct? Type 'yes' to push to Cloudflare: ")
    if confirm.lower() == 'yes':
        print("Pushing changes to Cloudflare...")
        try:
            subprocess.run(["dnscontrol", "push"], check=True)
            print("Cloudflare update complete.")
        except subprocess.CalledProcessError:
            print("\n[!] DNSControl push failed.", file=sys.stderr)
    else:
        print("Push aborted by user.")
    
    if not args.keep and os.path.exists(json_filename):
        os.remove(json_filename)
        print(f"Cleaned up {json_filename}")


# --- Internal DNS Helpers (SSH/SCP/TOML) ---

def build_hosts_block(entries: List[Dict[str, Any]], indent: str = '') -> str:
    unique_entries = {e['fqdn']: e['ip'] for e in entries}
    lines = [f'{indent}hosts = [']
    for fqdn, ip in unique_entries.items():
        val = f"{ip} {fqdn}"
        lines.append(f'{indent}  "{val}",')
    if lines:
        lines[-1] = lines[-1].rstrip(',')
    lines.append(f'{indent}]')
    return '\n'.join(lines) + '\n'

def replace_hosts_in_toml(content: str, new_block: str) -> str:
    # 1. Find [dns] section start
    dns_header_match = re.search(r'^\[dns\]\s*$', content, re.MULTILINE)
    if not dns_header_match:
        # Fallback: just append if no [dns] section found
        return content.rstrip() + '\n\n[dns]\n' + new_block

    section_start = dns_header_match.end()

    # 2. Find next section start (or EOF)
    # We search in the substring following [dns]
    next_section_match = re.search(r'^\[.+\]\s*$', content[section_start:], re.MULTILINE)
    if next_section_match:
        section_end = section_start + next_section_match.start()
    else:
        section_end = len(content)

    # 3. Extract [dns] content
    dns_content = content[section_start:section_end]

    # 4. Replace or Append 'hosts' within [dns]
    pattern = re.compile(r'(?ms)^\s*hosts\s*=\s*\[.*?\]\s*$', re.MULTILINE)
    
    if pattern.search(dns_content):
        new_dns_content = pattern.sub(new_block.rstrip() + '\n', dns_content)
    else:
        new_dns_content = dns_content.rstrip() + '\n\n' + new_block

    # 5. Reassemble
    return content[:section_start] + new_dns_content + content[section_end:]

def run_cmd(cmd: str, explanation: Optional[str] = None, dry_run: bool = False) -> Tuple[int, str, str]:
    if explanation:
        print(f"=> {explanation}")
    if dry_run:
        print(f"[Dry Run] CMD: {cmd}")
        return 0, '', ''
    p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode('utf-8', errors='ignore'), p.stderr.decode('utf-8', errors='ignore')

def get_sshpass_prefix(password: Optional[str]) -> str:
    if password and shutil.which("sshpass"):
        return f"sshpass -p {shlex.quote(password)} "
    return ""

def scp_to_remote(local_path: str, remote_user_host: str, remote_tmp_path: str, ssh_port: Optional[str] = None, password: Optional[str] = None, dry_run: bool = False) -> Tuple[int, str, str]:
    port_flag = f"-P {ssh_port}" if ssh_port else ""
    prefix = get_sshpass_prefix(password)
    cmd = f"{prefix}scp {port_flag} {shlex.quote(local_path)} {shlex.quote(remote_user_host)}:{shlex.quote(remote_tmp_path)}"
    return run_cmd(cmd, explanation=f"Copying file to {remote_user_host}:{remote_tmp_path}", dry_run=dry_run)

def scp_from_remote(remote_user_host: str, remote_path: str, local_path: str, ssh_port: Optional[str] = None, password: Optional[str] = None, dry_run: bool = False) -> Tuple[int, str, str]:
    port_flag = f"-P {ssh_port}" if ssh_port else ""
    prefix = get_sshpass_prefix(password)
    cmd = f"{prefix}scp {port_flag} {shlex.quote(remote_user_host)}:{shlex.quote(remote_path)} {shlex.quote(local_path)}"
    return run_cmd(cmd, explanation=f"Copying file from {remote_user_host}:{remote_path}", dry_run=dry_run)

def ssh_run(remote_user_host: str, remote_cmd: str, ssh_port: Optional[str] = None, password: Optional[str] = None, dry_run: bool = False) -> Tuple[int, str, str]:
    port_flag = f"-p {ssh_port}" if ssh_port else ""
    prefix = get_sshpass_prefix(password)
    
    # If using password, we might need to relax BatchMode or StrictHostKeyChecking if it interferes, 
    # but usually BatchMode=yes prevents password prompts. 
    # If we provide password via sshpass, we want ssh to accept it.
    # sshpass works by detecting the prompt. BatchMode=yes suppresses the prompt.
    # So we MUST remove BatchMode=yes if we are using sshpass.
    
    # Allow interactive password prompts if sshpass is not used (consistent with scp_to_remote)
    opts = ""
    
    cmd = f"{prefix}ssh {port_flag} {opts} {shlex.quote(remote_user_host)} {shlex.quote(remote_cmd)}"
    return run_cmd(cmd, explanation=f"Running remote command on {remote_user_host}", dry_run=dry_run)

def process_vlan_pihole(vlan: str, entries: List[Dict[str, Any]], server_config: Dict[str, Any], global_config: Dict[str, Any], dry_run: bool, backup: bool, reload_cmd_arg: Optional[str], keep_files: bool) -> None:
    if not entries:
        return

    vlan_lower = vlan.lower()
    
    # Resolve Remote Details
    remote_host = server_config.get('host')
    if not remote_host:
        remote_host = f"pihole.{vlan_lower}.moyer.wtf"
        print(f"  [Info] No host defined for {vlan} in config, defaulting to {remote_host}")

    ssh_user = server_config.get('user', global_config.get('ssh_user', 'root'))
    ssh_port = str(server_config.get('port', global_config.get('ssh_port', '22')))
    
    use_sudo = server_config.get('use_sudo', global_config.get('use_sudo', True))
    sudo_prefix = "sudo " if use_sudo else ""

    remote_path = "/etc/pihole/pihole.toml"
    remote_user_host = f"{ssh_user}@{remote_host}" if ssh_user else remote_host
    
    toml_filename = f"pihole-{vlan_lower}.toml"
    toml_path = os.path.abspath(toml_filename)

    print(f"Updating Pi-hole for VLAN {vlan} on {remote_host} (User: {ssh_user})...")

    # 1. Fetch Remote Config
    print(f"  Fetching current config from {remote_host}...")
    rc, _, err = scp_from_remote(remote_user_host, remote_path, toml_path, ssh_port=ssh_port, dry_run=dry_run)
    
    if rc != 0:
        if dry_run:
             print("  [Dry Run] Would fetch remote file. Assuming local file exists or creating new.")
        else:
             print(f"  [Warning] Could not fetch remote config: {err}")
             if not os.path.isfile(toml_path):
                 print(f"  [Error] No local copy of {toml_filename} found. Cannot proceed.")
                 return
             print(f"  Using existing local copy: {toml_path}")

    # 2. Read & Update Config
    content = ""
    if os.path.isfile(toml_path):
        with open(toml_path, 'r', encoding='utf-8') as f:
            content = f.read()
    elif dry_run:
        content = "# Dry Run Mock Content\n[dns]\nhosts = []\n"
    else:
        print(f"  [Error] File {toml_path} not found after fetch attempt.")
        return

    new_block = build_hosts_block(entries)
    new_content = replace_hosts_in_toml(content, new_block)

    if dry_run:
        tmp_local = os.path.join("dry-run", f"pihole-{vlan_lower}.toml")
        with open(tmp_local, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"  [Dry Run] Generated local file: {tmp_local}")
    else:
        tmp_local = toml_path
        with open(tmp_local, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"  Updated local file: {tmp_local}")

    # 3. Push Config Back
    remote_tmp = f"/tmp/pihole.toml.{os.getpid()}.{vlan}"

    if backup:
        ts = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        backup_cmd = f"{sudo_prefix}cp {shlex.quote(remote_path)} {shlex.quote(remote_path + '.bak-' + ts)}"
        ssh_run(remote_user_host, backup_cmd, ssh_port=ssh_port, dry_run=dry_run)

    rc, _, err = scp_to_remote(tmp_local, remote_user_host, remote_tmp, ssh_port=ssh_port, dry_run=dry_run)
    if rc != 0:
        print(f"  Error copying file: {err}")
        return

    mv_cmd = f"{sudo_prefix}mv {shlex.quote(remote_tmp)} {shlex.quote(remote_path)} && {sudo_prefix}chown root:root {shlex.quote(remote_path)} && {sudo_prefix}chmod 644 {shlex.quote(remote_path)}"
    rc, _, err = ssh_run(remote_user_host, mv_cmd, ssh_port=ssh_port, dry_run=dry_run)
    if rc != 0:
        print(f"  Error moving file into place: {err}")
        return

    reload_cmd = reload_cmd_arg or f'{sudo_prefix}pihole restartdns'
    rc, _, err = ssh_run(remote_user_host, reload_cmd, ssh_port=ssh_port, dry_run=dry_run)
    if rc == 0:
        print(f"  Success: Reloaded DNS on {remote_host}")
    
    if not keep_files and os.path.exists(toml_path):
        os.remove(toml_path)
        print(f"  Cleaned up local file: {toml_path}")

def deploy_mikrotik_script(filename: str, lines: List[str], host: str, user: str, port: str, password: Optional[str], dry_run: bool, keep_files: bool) -> None:
    content = "\n".join(lines) + "\n"
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        if dry_run:
            print(f"  [Dry Run] Generated local file: {filename}")
            if not keep_files:
                # In dry run we might want to keep it to inspect, but user said "unless --keep is used"
                # But usually dry run is for inspection.
                # However, the prompt says "After a successful run, delete ... unless ... --keep is used".
                # I'll assume keep_files applies to dry run too if we want to inspect.
                pass
            return
    except Exception as e:
        print(f"  Error writing local RSC: {e}")
        return

    remote_user_host = f"{user}@{host}" if user else host
    remote_rsc_path = filename # Use same name on remote
    
    rc, _, err = scp_to_remote(filename, remote_user_host, remote_rsc_path, ssh_port=port, password=password, dry_run=dry_run)
    if rc == 0:
        import_cmd = f"/import file={remote_rsc_path}; /file remove [find name=\"{remote_rsc_path}\"]"
        rc_run, _, err_run = ssh_run(remote_user_host, import_cmd, ssh_port=port, password=password, dry_run=dry_run)
        if rc_run == 0:
            print(f"  Success: Imported {filename} on {host}")
        else:
            print(f"  Error running import on Mikrotik: {err_run}")
    else:
        print(f"  Error copying file: {err}")
    
    if not dry_run and not keep_files and os.path.exists(filename):
        os.unlink(filename)

def process_vlan_mikrotik(vlan: str, dns_entries: List[Dict[str, Any]], firewall_entries: List[Dict[str, Any]], nat_entries: List[Dict[str, Any]], server_config: Dict[str, Any], global_config: Dict[str, Any], dry_run: bool, caddy_ip: Optional[str], wan_interface: str, router_host: Optional[str] = None, router_user: Optional[str] = None, router_port: Optional[str] = None, password: Optional[str] = None, keep_files: bool = False) -> None:
    if not dns_entries and not firewall_entries and not nat_entries:
        return
    vlan_lower = vlan.lower()
    
    target_host = router_host or server_config.get('host')
    
    if not target_host:
        print(f"Skipping Mikrotik update for VLAN '{vlan_lower}': No host mapping found in config.")
        return

    ssh_user = router_user or server_config.get('user', global_config.get('ssh_user', 'root'))
    ssh_port = str(router_port or server_config.get('port', global_config.get('ssh_port', '22')))

    print(f"Updating Mikrotik for VLAN {vlan} on {target_host} (User: {ssh_user})...")
    
    # --- 1. DNS Update ---
    if dns_entries:
        dns_script_comment = f"Generated by update-network-configs.py (DNS: {vlan_lower})"
        dns_filename = f"mikrotik-{vlan_lower}-dns.rsc"
        if dry_run:
            dns_filename = os.path.join("dry-run", dns_filename)
        
        dns_lines = [
            f"# Generated by update-network-configs.py on {datetime.datetime.now()}",
            f":put \"Starting DNS update for VLAN: {vlan_lower}\"",
            "/ip dns static",
            f'remove [find comment="{dns_script_comment}"]',
            ':put "Updating DNS entries..."'
        ]
        
        unique_dns = {e['fqdn']: e['ip'] for e in dns_entries}
        for fqdn, ip in unique_dns.items():
            cmd = f'add name="{fqdn}" address="{ip}" comment="{dns_script_comment}"'
            dns_lines.append(cmd)
            
        deploy_mikrotik_script(dns_filename, dns_lines, target_host, ssh_user, ssh_port, password, dry_run, keep_files)

    # --- 2. Firewall Update ---
    # Only proceed if Caddy IP is known AND at least one entry has ports defined
    has_ports = any(e.get('ports') for e in firewall_entries)
    
    if caddy_ip and firewall_entries and has_ports:
        fw_script_comment = f"Generated by update-network-configs.py (FW: {vlan_lower})"
        fw_filename = f"mikrotik-{vlan_lower}-firewall.rsc"
        if dry_run:
            fw_filename = os.path.join("dry-run", fw_filename)
        
        fw_lines = [
            f"# Generated by update-network-configs.py on {datetime.datetime.now()}",
            f":put \"Starting Firewall update for VLAN: {vlan_lower}\"",
            "/ip firewall filter",
            f'remove [find comment="{fw_script_comment}"]',
            ':put "Updating Caddy Pinholes..."'
        ]

        for e in firewall_entries:
            raw_ports = e.get('ports')
            target_ip = e['ip']
            
            if raw_ports and target_ip:
                if caddy_ip == target_ip:
                    print(f"  [Firewall] Skipping rule for {target_ip}: Source and Destination are the same.")
                    continue

                # Parse format: "80/TCP, 443/TCP, 19132/UDP"
                tcp_ports = []
                udp_ports = []
                
                port_entries = [p.strip() for p in raw_ports.split(',') if p.strip()]
                
                for item in port_entries:
                    # Split into number and protocol
                    if '/' in item:
                        parts = item.split('/', 1)
                        p_num = parts[0].strip()
                        p_proto = parts[1].strip().lower()
                    else:
                        # Fallback if just number is provided
                        p_num = item.strip()
                        p_proto = 'tcp'
                    
                    if p_proto == 'tcp':
                        tcp_ports.append(p_num)
                    elif p_proto == 'udp':
                        udp_ports.append(p_num)

                # Generate TCP Rule
                if tcp_ports:
                    ports_joined = ','.join(tcp_ports)
                    rule_tcp = (
                        f'add chain=forward action=accept '
                        f'src-address={caddy_ip} dst-address={target_ip} '
                        f'protocol=tcp dst-port={ports_joined} '
                        f'place-before=[find comment="Drop invalid/inter-VLAN forward"] '
                        f'comment="{fw_script_comment}"'
                    )
                    fw_lines.append(rule_tcp)
                    print(f"  [Firewall] Added TCP rule for {target_ip}: {ports_joined}")

                # Generate UDP Rule
                if udp_ports:
                    ports_joined = ','.join(udp_ports)
                    rule_udp = (
                        f'add chain=forward action=accept '
                        f'src-address={caddy_ip} dst-address={target_ip} '
                        f'protocol=udp dst-port={ports_joined} '
                        f'place-before=[find comment="Drop invalid/inter-VLAN forward"] '
                        f'comment="{fw_script_comment}"'
                    )
                    fw_lines.append(rule_udp)
                    print(f"  [Firewall] Added UDP rule for {target_ip}: {ports_joined}")
        
        deploy_mikrotik_script(fw_filename, fw_lines, target_host, ssh_user, ssh_port, password, dry_run, keep_files)

    elif any(e.get('ports') for e in firewall_entries):
        print(f"  [Warning] Service Ports found for VLAN {vlan}, but --caddy-ip was not provided. Skipping firewall rules.")

    # --- 3. NAT Update ---
    if nat_entries:
        nat_script_comment = f"Generated by update-network-configs.py (NAT: {vlan_lower})"
        nat_filename = f"mikrotik-{vlan_lower}-nat.rsc"
        if dry_run:
            nat_filename = os.path.join("dry-run", nat_filename)
        
        nat_lines = [
            f"# Generated by update-network-configs.py on {datetime.datetime.now()}",
            f":put \"Starting NAT update for VLAN: {vlan_lower}\"",
            "/ip firewall nat",
            f'remove [find comment="{nat_script_comment}"]',
            ':put "Updating NAT rules..."'
        ]
        
        seen_nat_rules = set()

        for e in nat_entries:
            raw_ports = e.get('ports')
            target_ip = e['ip']
            
            if raw_ports and target_ip:
                # Parse format: "80/TCP, 443/TCP"
                port_entries = [p.strip() for p in raw_ports.split(',') if p.strip()]
                
                for item in port_entries:
                    if '/' in item:
                        parts = item.split('/', 1)
                        p_num = parts[0].strip()
                        p_proto = parts[1].strip().lower()
                    else:
                        p_num = item.strip()
                        p_proto = 'tcp'
                    
                    # Deduplicate
                    rule_key = (target_ip, p_num, p_proto)
                    if rule_key in seen_nat_rules:
                        continue
                    seen_nat_rules.add(rule_key)

                    # Generate NAT Rule
                    rule = (
                        f'add chain=dstnat action=dst-nat '
                        f'to-addresses={target_ip} to-ports={p_num} '
                        f'protocol={p_proto} dst-port={p_num} '
                        f'in-interface={wan_interface} '
                        f'comment="{nat_script_comment}"'
                    )
                    nat_lines.append(rule)
                    print(f"  [NAT] Added rule for {target_ip}: {p_num}/{p_proto}")
        
        deploy_mikrotik_script(nat_filename, nat_lines, target_host, ssh_user, ssh_port, password, dry_run, keep_files)


def find_closing_brace(text: str, start_index: int) -> int:
    depth = 1
    for i, char in enumerate(text[start_index:], start=start_index):
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return i
    return -1

def process_caddyfile(records: List[Dict[str, str]], caddyfile_path: str, dry_run: bool) -> None:
    if not records:
        return

    print(f"\n=== Processing Caddyfile Map ({len(records)} entries) ===")
    
    if not os.path.isfile(caddyfile_path):
        print(f"[!] Error: Caddyfile not found at {caddyfile_path}", file=sys.stderr)
        return

    try:
        with open(caddyfile_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"[!] Error reading Caddyfile: {e}", file=sys.stderr)
        return

    # 1. Find all site blocks and their maps
    # Regex for site block start: start of line, non-whitespace chars (including comma), space, brace
    # We want to capture the domain list.
    site_start_re = re.compile(r'(?m)^([^\s{]+(?:,\s*[^\s{]+)*)\s+\{')
    
    blocks = [] # List of dicts: {domains: [], map_match: match_object, start: int, end: int}
    
    for match in site_start_re.finditer(content):
        domain_str = match.group(1)
        start_idx = match.end()
        end_idx = find_closing_brace(content, start_idx)
        
        if end_idx == -1:
            print(f"[Warning] Could not find closing brace for block: {domain_str}")
            continue
            
        block_content = content[start_idx:end_idx]
        
        # Find map inside block
        map_match = re.search(r'(map\s+\{host\}\s+\{backend\}\s+\{)(.*?)(\n\s+\})', block_content, re.DOTALL)
        
        if map_match:
            # Parse domains
            # Remove *. prefix
            domains = []
            for d in domain_str.split(','):
                d = d.strip()
                if d.startswith('*.'):
                    domains.append(d[2:])
                else:
                    domains.append(d)
            
            blocks.append({
                'domains': domains,
                'map_match': map_match,
                'block_start': start_idx,
                'block_end': end_idx
            })

    if not blocks:
        print("[!] Error: No 'map {host} {backend}' blocks found in Caddyfile.", file=sys.stderr)
        return

    # 2. Assign records to blocks
    # We map each block index to a list of records
    block_records = {i: [] for i in range(len(blocks))}
    
    for r in records:
        fqdn = r['host']
        best_block_idx = -1
        max_match_len = -1
        
        for i, block in enumerate(blocks):
            for d in block['domains']:
                # Check if fqdn ends with domain (and is preceded by dot or is exact match)
                if fqdn == d or fqdn.endswith('.' + d):
                    if len(d) > max_match_len:
                        max_match_len = len(d)
                        best_block_idx = i
        
        if best_block_idx != -1:
            block_records[best_block_idx].append(r)
        else:
            print(f"  [Warning] No matching Caddyfile block found for: {fqdn}")

    # 3. Generate updates
    edits = [] # (start, end, replacement)
    
    for i, block in enumerate(blocks):
        recs = block_records[i]
        if not recs:
            continue
            
        print(f"  Updating block for domains {block['domains']}: {len(recs)} records")
        
        # Build new map content
        max_host_len = max(len(r['host']) for r in recs) if recs else 0
        indent = "        "
        
        lines = []
        for r in recs:
            host = r['host']
            backend = r['backend']
            padding = " " * (max_host_len - len(host) + 4)
            lines.append(f"{indent}{host}{padding}{backend}")
        
        new_map_body = "\n".join(lines)
        
        map_match = block['map_match']
        existing_block = map_match.group(2)
        has_default = "default" in existing_block and "unknown" in existing_block
        
        final_replacement = f"{map_match.group(1)}\n{indent}# Generated by update-network-configs.py on {datetime.datetime.now()}\n{new_map_body}\n"
        
        if has_default:
            final_replacement += f"\n{indent}default                 unknown"
            
        final_replacement += map_match.group(3)
        
        # Calculate absolute positions
        abs_start = block['block_start'] + map_match.start()
        abs_end = block['block_start'] + map_match.end()
        
        edits.append((abs_start, abs_end, final_replacement))

    # 4. Apply edits
    if not edits:
        print("  No changes to apply.")
        return

    # Sort edits reverse to apply safely
    edits.sort(key=lambda x: x[0], reverse=True)
    
    new_content = content
    for start, end, repl in edits:
        new_content = new_content[:start] + repl + new_content[end:]
    
    if dry_run:
        dryrun_path = os.path.join("dry-run", "Caddyfile")
        with open(dryrun_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"  [Dry Run] Generated local file: {dryrun_path}")
    else:
        with open(caddyfile_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated Caddyfile: {caddyfile_path}")


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description='Update Pi-hole (Internal), Mikrotik (Internal), and Cloudflare (External) DNS.')
    parser.add_argument('--config', default='dns-config.toml', help='Path to configuration TOML file')
    parser.add_argument('--inventory', '-i', help='Path to System Inventory CSV or Google Sheet URL (overrides config)')
    parser.add_argument('--caddy-ip', help='IP address of the Caddy Reverse Proxy (overrides config)')
    parser.add_argument('--caddyfile', help='Path to Caddyfile (overrides config, default: Caddyfile)')
    parser.add_argument('--wan-interface', help='WAN interface for NAT rules (default: ether1)')
    parser.add_argument('--ssh-user', help='Default ssh user (overrides config)')
    parser.add_argument('--ssh-port', help='Default SSH port (overrides config)')
    parser.add_argument('--dry-run', action='store_true', help='Show actions without making changes')
    parser.add_argument('--backup', action='store_true', help='Create backup of remote files')
    parser.add_argument('--reload-cmd', help='Command to reload Pi-hole DNS')
    parser.add_argument('--vlan', action='append', help='Specify VLANs to update (can be used multiple times). Use "none" to skip all local updates.')
    parser.add_argument('--keep', action='store_true', help='Keep generated and downloaded files')
    parser.add_argument('--skip-firewall', action='store_true', help='Skip Mikrotik firewall rule generation')
    parser.add_argument('--skip-cloudflare', action='store_true', help='Skip Cloudflare DNSControl processing')
    parser.add_argument('--skip-caddy', action='store_true', help='Skip Caddyfile update')

    args = parser.parse_args(argv)

    # 1. Load Config
    config = load_config(args.config)
    
    if args.dry_run:
        os.makedirs("dry-run", exist_ok=True)
    
    # 2. Resolve Global Settings (CLI > Config > Default)
    inventory_input = args.inventory or config.get('inventory')
    if not inventory_input:
        print("Error: Inventory file/URL must be specified via --inventory or config file.", file=sys.stderr)
        sys.exit(1)

    # Handle URL vs File
    inventory_path, is_temp_file = fetch_inventory_csv(inventory_input)

    caddy_ip = args.caddy_ip or config.get('caddy_ip')
    caddyfile_path = args.caddyfile or config.get('caddyfile', 'Caddyfile')
    wan_interface = args.wan_interface or config.get('wan_interface', 'ether1')
    
    # Update global config dict with resolved defaults for passing down
    global_config = {
        'ssh_user': args.ssh_user or config.get('ssh_user', 'root'),
        'ssh_port': args.ssh_port or config.get('ssh_port', 22),
        'router_host': config.get('router_host'),
        'router_user': config.get('router_user'),
        'router_port': config.get('router_port', 22),
        'use_sudo': config.get('use_sudo', False)
    }

    # 3. Check Prerequisites
    if not check_prerequisites(needs_dnscontrol=True):
        sys.exit(1)

    # 4. Process Internal Config
    servers_config = config.get('servers', {})
    user_vlan = config.get('user_vlan')
    
    # Get Router Password (from config or prompt once)
    router_password = config.get('router_password')

    # 5. Parse CSV
    print(f"Reading inventory: {inventory_path}")
    groups, cf_records, caddy_records = parse_inventory_csv(inventory_path, servers_config, user_vlan, caddy_ip)

    # 6. Process Internal Groups
    if groups:
        # Filter groups based on --vlan argument
        if args.vlan:
            normalized_vlans = [v.lower() for v in args.vlan]
            if 'none' in normalized_vlans:
                print("\n=== Skipping Internal DNS & Firewall (User requested 'none') ===")
                groups = {}
            else:
                # Filter groups to only those specified
                groups = {k: v for k, v in groups.items() if k.lower() in normalized_vlans}
                if not groups:
                     print(f"\n[Warning] No matching VLANs found for: {', '.join(args.vlan)}")

        if groups:
            print("\n=== Processing Internal DNS & Firewall ===")
            for vlan, providers in groups.items():
                # Get server config for this VLAN
                # Try exact match, then lowercase
                server_conf = servers_config.get(vlan) or servers_config.get(vlan.lower(), {})
                
                # Pi-hole
                if providers['pihole']:
                    # If type is explicitly mikrotik in config, but we have pihole records, 
                    # we might want to warn or just proceed if the user knows what they are doing.
                    # But here we just pass the config.
                    process_vlan_pihole(
                        vlan, 
                        providers['pihole'], 
                        server_conf, 
                        global_config, 
                        args.dry_run, 
                        args.backup, 
                        args.reload_cmd,
                        args.keep
                    )
                
                # Mikrotik
                # We want to process Mikrotik if we have ANY entries (for firewall) OR if we have mikrotik DNS entries.
                # AND if the server config supports it (type == mikrotik) OR we have a router defined.
                
                all_entries = providers['pihole'] + providers['mikrotik']
                
                # Check if we have any ports defined (requiring firewall rules)
                has_ports = any(e.get('ports') for e in all_entries)
                
                # Determine target router
                router_host = server_conf.get('router')
                router_user = server_conf.get('router_user')
                router_port = server_conf.get('router_port')

                # If not explicitly set, and this server IS a Mikrotik, use its host details
                if not router_host and server_conf.get('type') == 'mikrotik':
                    router_host = server_conf.get('host')
                    router_user = server_conf.get('user')
                    router_port = server_conf.get('port')

                # Fallback to Global Router Config
                if not router_host:
                    router_host = global_config.get('router_host')
                    router_user = global_config.get('router_user')
                    router_port = global_config.get('router_port')

                should_process_firewall = has_ports and caddy_ip and not args.skip_firewall
                should_process_dns = bool(providers['mikrotik']) and (server_conf.get('type') == 'mikrotik')
                should_process_nat = bool(providers.get('nat'))
                
                if router_host and (should_process_dns or should_process_firewall or should_process_nat):
                    # Prompt for password if needed and not yet obtained
                    if not router_password and not args.dry_run:
                         # Check if we have sshpass
                         if shutil.which("sshpass"):
                             print(f"\n[Input] Enter SSH password for Mikrotik ({router_user or 'root'}@{router_host}):")
                             router_password = getpass.getpass()
                         else:
                             # If no sshpass, we can't help much, but maybe we shouldn't prompt?
                             # Or just let it be None and let ssh prompt.
                             pass

                    process_vlan_mikrotik(
                        vlan, 
                        dns_entries=providers['mikrotik'],
                        firewall_entries=all_entries,
                        nat_entries=providers.get('nat', []),
                        server_config=server_conf, 
                        global_config=global_config, 
                        dry_run=args.dry_run, 
                        caddy_ip=caddy_ip,
                        wan_interface=wan_interface,
                        router_host=router_host,
                        router_user=router_user,
                        router_port=router_port,
                        password=router_password,
                        keep_files=args.keep
                    )
                elif should_process_firewall and not router_host:
                    print(f"  [Warning] VLAN {vlan} has Service Ports but no Mikrotik router configured. Skipping firewall rules.")

    # 7. Process Caddyfile
    if not args.skip_caddy and caddy_records:
        abs_caddyfile_path = os.path.abspath(caddyfile_path)
        if not os.path.isfile(abs_caddyfile_path):
            print(f"[!] Error: Caddyfile not found at {abs_caddyfile_path}", file=sys.stderr)
            sys.exit(1)
            
        process_caddyfile(caddy_records, abs_caddyfile_path, args.dry_run)

    # 8. Process External
    if not args.skip_cloudflare:
        print("\n=== Processing External DNS Records (Cloudflare) ===")
        process_dnscontrol(cf_records, args)
    else:
        print("\n=== Skipping External DNS Records (User requested skip) ===")

    # Cleanup temp file if needed
    if is_temp_file and os.path.exists(inventory_path):
        try:
            os.unlink(inventory_path)
            print(f"Cleaned up temporary file: {inventory_path}")
        except OSError as e:
            print(f"Warning: Could not delete temp file {inventory_path}: {e}", file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))