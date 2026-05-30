# Adding a new node

1. Add the node to the Nodes tab of the Google Sheet
2. Run the automation scripts:
    - Ansible: Bootstrap script
    - Ansible: Hardening script
    - Optional: Tailscale

# Adding a new service

1. Add one row per exposed service to the Services tab of the Google Sheet
2. Add any reusable MikroTik address-list rows to the Static Address Lists tab when needed
3. Run the installation script for the service:
    - Ansible playbook
    - Python Homelab: Deploy (preferred method)
4. Run the automation scripts:
    - Python Homelab: DNS, Caddy, and Mikrotik
5. Deploy the generated service files for Mikrotik manually
6. Configure any backups