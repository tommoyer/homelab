# Adding a new node

1. Add the node to the Nodes tab of the Google Sheet
2. Run the automation scripts:
    - Ansible: Bootstrap script
    - Ansible: Hardening script
    - Optional: Tailscale

# Adding a new service

1. Add one row per exposed service to the Services tab of the Google Sheet
2. Run the installation script for the service:
    - Ansible playbook
    - Python Homelab: Deploy (preferred method)
3. Run the automation scripts:
    - Python Homelab: Pihole, Caddy, Mikrotik, dnsmasq, and dnscontrol
4. Deploy the generated service files for Mikrotik manually
5. Configure any backups