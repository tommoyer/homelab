variable "proxmox_endpoint" {
  type = string
}

variable "proxmox_insecure" {
  type    = bool
  default = false
}

variable "proxmox_ssh_username" {
  type    = string
  default = "root"
}

variable "default_node_name" {
  type = string
}

variable "default_template_file_id" {
  type = string
}

variable "default_datastore_id" {
  type = string
}

variable "default_bridge" {
  type    = string
  default = "vmbr0"
}

variable "default_vlan_id" {
  type    = number
  default = 1
}

variable "ssh_public_keys" {
  type    = list(string)
  default = []
}

