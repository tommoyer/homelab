output "container_name" {
  value = var.hostname
}

output "container_ipv4_cidr" {
  value = var.ipv4_cidr
}

output "container_password" {
  value     = random_password.container_password.result
  sensitive = true
}