output "netbox_name" {
  value = module.netbox.container_name
}

output "netbox_ipv4_cidr" {
  value = module.netbox.container_ipv4_cidr
}

output "netbox_password" {
  value     = module.netbox.container_password
  sensitive = true
}