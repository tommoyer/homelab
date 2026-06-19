# OpenTofu module-based layout for Proxmox LXCs

This guide shows a simple next-step layout for growing from a single proof-of-concept container into multiple Proxmox LXC guests managed with OpenTofu. OpenTofu recommends a root module for composition and separate child modules for reusable building blocks, with `main.tf`, `variables.tf`, and `outputs.tf` forming the standard structure for each module [cite:242][cite:245]. OpenTofu also treats all `.tf` files in a directory as one module, so splitting files is for maintainability rather than execution order [cite:247].

## Goal

The goal is to keep the root of the `tofu/` directory focused on **which containers exist**, while a reusable child module handles **how one Debian LXC is created** [cite:242][cite:240]. This is a better long-term shape than leaving a literal `netbox` resource in the root `main.tf` once additional services are added [cite:241][cite:251].

## Directory structure

Use a layout like this:

```text
tofu/
├── README.md
├── versions.tf
├── providers.tf
├── variables.tf
├── outputs.tf
├── locals.tf
├── main.tf
├── terraform.tfvars
└── modules/
    └── proxmox-lxc/
        ├── main.tf
        ├── variables.tf
        ├── outputs.tf
```

In this layout, the root module wires together service instances, and the `modules/proxmox-lxc` directory defines a reusable Debian LXC pattern [cite:242][cite:245].

## Create the directories

Run:

```bash
mkdir -p modules/proxmox-lxc
```

## Root module files

Create `versions.tf`:

```bash
cat > versions.tf <<EOF
terraform {
  required_version = ">= 1.8.0"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.70"
    }
  }
}
EOF
```

Create `providers.tf`:

```bash
cat > providers.tf <<EOF
provider "proxmox" {
  endpoint  = var.proxmox_endpoint
  api_token = var.proxmox_api_token
  insecure  = var.proxmox_insecure

  ssh {
    agent    = true
    username = var.proxmox_ssh_username
  }
}
EOF
```

Create `variables.tf`:

```bash
cat > variables.tf <<EOF
variable "proxmox_endpoint" {
  type = string
}

variable "proxmox_api_token" {
  type      = string
  sensitive = true
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
  default = 0
}

variable "ssh_public_keys" {
  type    = list(string)
  default = []
}
EOF
```

Create `locals.tf`:

```bash
cat > locals.tf <<EOF
locals {
  containers = {
    netbox = {
      hostname     = "netbox-0"
      ipv4_cidr    = "192.168.30.50/24"
      ipv4_gateway = "192.168.30.1"
      memory_mb    = 2048
      disk_size_gb = 16
      cpu_cores    = 2
    }

    mealie = {
      hostname     = "mealie-0"
      ipv4_cidr    = "192.168.30.51/24"
      ipv4_gateway = "192.168.30.1"
      memory_mb    = 1024
      disk_size_gb = 10
      cpu_cores    = 2
    }
  }
}
EOF
```

Create `main.tf`:

```bash
cat > main.tf <<EOF
module "containers" {
  source = "./modules/proxmox-lxc"

  for_each = local.containers

  node_name        = var.default_node_name
  hostname         = each.value.hostname
  template_file_id = var.default_template_file_id
  datastore_id     = var.default_datastore_id
  bridge           = var.default_bridge
  vlan_id          = var.default_vlan_id
  ipv4_cidr        = each.value.ipv4_cidr
  ipv4_gateway     = each.value.ipv4_gateway
  cpu_cores        = each.value.cpu_cores
  memory_mb        = each.value.memory_mb
  disk_size_gb     = each.value.disk_size_gb
  ssh_public_keys  = var.ssh_public_keys
}
EOF
```

Create `outputs.tf`:

```bash
cat > outputs.tf <<EOF
output "container_names" {
  value = {
    for name, mod in module.containers : name => mod.container_name
  }
}

output "container_ipv4_cidrs" {
  value = {
    for name, mod in module.containers : name => mod.container_ipv4_cidr
  }
}
EOF
```

Create `terraform.tfvars`:

```bash
cat > terraform.tfvars <<EOF
proxmox_endpoint         = "https://proxmox.example.com:8006/api2/json"
proxmox_api_token        = "root@pam!tofu=REPLACE_ME"
proxmox_insecure         = true
proxmox_ssh_username     = "root"

default_node_name        = "pve-0"
default_template_file_id = "local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst"
default_datastore_id     = "local-lvm"
default_bridge           = "vmbr0"
default_vlan_id          = 30

ssh_public_keys = [
  "ssh-ed25519 AAAA...replace-me... your-key"
]
EOF
```

## Child module files

Create `modules/proxmox-lxc/main.tf`:

```bash
cat > modules/proxmox-lxc/main.tf <<EOF
resource "proxmox_virtual_environment_container" "this" {
  node_name    = var.node_name
  hostname     = var.hostname
  started      = true
  unprivileged = true

  operating_system {
    template_file_id = var.template_file_id
    type             = "debian"
  }

  cpu {
    cores = var.cpu_cores
  }

  memory {
    dedicated = var.memory_mb
    swap      = 512
  }

  disk {
    datastore_id = var.datastore_id
    size         = var.disk_size_gb
  }

  network_interface {
    name    = "eth0"
    bridge  = var.bridge
    vlan_id = var.vlan_id
  }

  initialization {
    hostname = var.hostname

    ip_config {
      ipv4 {
        address = var.ipv4_cidr
        gateway = var.ipv4_gateway
      }
    }

    user_account {
      keys = var.ssh_public_keys
    }
  }
}
EOF
```

Create `modules/proxmox-lxc/variables.tf`:

```bash
cat > modules/proxmox-lxc/variables.tf <<EOF
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
EOF
```

Create `modules/proxmox-lxc/outputs.tf`:

```bash
cat > modules/proxmox-lxc/outputs.tf <<EOF
output "container_name" {
  value = proxmox_virtual_environment_container.this.hostname
}

output "container_ipv4_cidr" {
  value = var.ipv4_cidr
}
EOF
```

## Initialize and apply

From the root `tofu/` directory, run:

```bash
tofu init
tofu plan
tofu apply
```

OpenTofu can generate unique IDs automatically for created VMs and containers when `vm_id` is omitted, which is a good fit for an early proof-of-concept [cite:167][cite:205]. The `bpg/proxmox` provider’s container resource is intended for managing Proxmox LXC containers in this style [cite:208].

## How to add another service

To add a new service container later, add another entry to `locals.containers` in `locals.tf` and rerun OpenTofu. That keeps the module code unchanged while the root module simply declares one more desired guest, which is the main value of this structure [cite:240][cite:241].

For example:

```hcl
bookstack = {
  hostname     = "bookstack-0"
  ipv4_cidr    = "192.168.30.52/24"
  ipv4_gateway = "192.168.30.1"
  memory_mb    = 1024
  disk_size_gb = 10
  cpu_cores    = 2
}
```

## Why this is better than keeping everything in root

This structure gives a clean separation between:
- provider and environment configuration in the root module,
- per-service desired state in `locals.tf`,
- reusable container build logic in the child module [cite:242][cite:245].

That makes it much easier to add NetBox now and more services later without turning `main.tf` into a long list of nearly identical resources [cite:241][cite:251].
