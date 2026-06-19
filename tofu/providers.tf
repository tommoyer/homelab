provider "proxmox" {
  endpoint  = var.proxmox_endpoint
  insecure  = var.proxmox_insecure

  ssh {
    agent    = true
    username = var.proxmox_ssh_username
  }
}
