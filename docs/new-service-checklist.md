# Adding a new node

1. Add the device and interfaces to NetBox under Devices
2. Assign the appropriate IP addresses and FQDN under IPAM
3. Add device to firewall rules for Grafana
4. Add any UIs to Application Services under IPAM

# Adding a new service

1. Add the virtual machine to NetBox under Virtualization
2. Assign the appropriate IP address and FQDN under IPAM
3. Add VM to firewall rules for Grafana (if applicable)
4. Add any UIs to Application Services under IPAM
5. Update firewall rules
6. Update NAT policies

# Update network configurations

1. Update DNS
2. Update Caddy
3. Update firewall
4. Update NAT