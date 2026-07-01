output "phpipam_name" {
  value = module.phpipam.container_name
}

output "phpipam_ipv4_cidr" {
  value = module.phpipam.container_ipv4_cidr
}

output "phpipam_password" {
  value     = module.phpipam.container_password
  sensitive = true
}