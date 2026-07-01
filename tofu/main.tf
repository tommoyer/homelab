module "phpipam" {
  source = "./modules/proxmox-lxc"

  node_name        = var.default_node_name
  hostname         = "phpipam"
  template_file_id = var.default_template_file_id
  datastore_id     = var.default_datastore_id
  bridge           = var.default_bridge
  vlan_id          = 10
  ipv4_cidr        = "192.168.10.17/24"
  ipv4_gateway     = "192.168.10.1"
  dns_servers      = ["192.168.100.2"]
  dns_domain       = "moyer.wtf"
  cpu_cores        = 2
  memory_mb        = 2048
  disk_size_gb     = 16
  ssh_public_keys  = var.ssh_public_keys
}