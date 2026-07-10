output "glance_name" {
  value = module.glance.container_name
}

output "glance_ipv4_cidr" {
  value = module.glance.container_ipv4_cidr
}

output "glance_password" {
  value     = module.glance.container_password
  sensitive = true
}