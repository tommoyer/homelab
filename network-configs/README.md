Update Pi-hole hosts helper

This folder contains `update_pihole_hosts.py`, a helper script that reads the
System Inventory CSV, generates the hosts list for each VLAN, and updates the
corresponding DNS server.

Supported DNS Providers:
- **pihole** (default): Updates `hosts = [...]` in `pihole.toml` and reloads remote Pi-hole.
- **mikrotik**: Generates a `.rsc` file with RouterOS commands to set static DNS entries.

Configuration

The script uses a standardized naming convention based on the VLAN name found in the inventory:
- **Local TOML**: `pihole-<vlan-name>.toml` (in the current directory)
- **Remote Host**: `pihole.<vlan-name>.moyer.wtf`
- **Remote Path**: `/etc/pihole/pihole.toml`
- **SSH User**: `root` (default)
- **SSH Port**: `22` (default)

Mikrotik Output
- Files named `mikrotik-<vlan-name>-dns-entries.rsc` will be generated in the current directory.
- These files contain `/ip dns static add` commands to be manually executed on the router.
- A mapping file `mikrotik_mapping.toml` is used to map VLAN names to router hostnames/IPs.
  You can specify a custom path with `--dns-server-mapping`.
  Example:
  ```toml
  hivemind = "192.168.1.1"
  ```

Quick example

1. Run the updater in dry-run mode to preview actions:

   python update_pihole_hosts.py --inventory "System Inventory - Nodes.csv" --dry-run

2. Run for real (recommended to use SSH keys and `--backup`):

   python update_pihole_hosts.py --inventory "System Inventory - Nodes.csv" --backup

Notes
- The script uses `ssh` and `scp` to copy files and run commands on remote hosts.
- It expects to be able to run `sudo mv` and `sudo pihole restartdns` on the remote host.
- You can override the default SSH user and port with `--ssh-user` and `--ssh-port`.

Security
- Use SSH keys and restrict access to the machine running this script. The
  script does not manage credentials.
