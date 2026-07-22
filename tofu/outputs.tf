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

output "firefly-iii_name" {
  value = module.firefly-iii.container_name
}

output "firefly-iii_ipv4_cidr" {
  value = module.firefly-iii.container_ipv4_cidr
}

output "firefly-iii_password" {
  value     = module.firefly-iii.container_password
  sensitive = true
}