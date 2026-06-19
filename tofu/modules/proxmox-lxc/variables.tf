variable "node_name" {
  type = string
}

variable "hostname" {
  type = string
}

variable "template_file_id" {
  type = string
}

variable "datastore_id" {
  type = string
}

variable "bridge" {
  type = string
}

variable "vlan_id" {
  type = number
}

variable "ipv4_cidr" {
  type = string
}

variable "ipv4_gateway" {
  type = string
}

variable "cpu_cores" {
  type = number
}

variable "memory_mb" {
  type = number
}

variable "disk_size_gb" {
  type = number
}

variable "ssh_public_keys" {
  type    = list(string)
  default = []
}

variable "dns_servers" {
  type    = list(string)
  default = []
}

variable "dns_domain" {
  type = string
}
