proxmox_endpoint         = "https://proxmox.priv.moyer.wtf/api2/json"
proxmox_insecure         = false
proxmox_ssh_username     = "root"

default_node_name        = "desktop-0"
default_template_file_id = "cephfs:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst"
default_datastore_id     = "rbd"
default_bridge           = "vmbr0"
default_vlan_id          = 30

ssh_public_keys = [
  "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILGyVvDIDOgBHJmrWVbcvvVE5Og6MBWf3eWQTBZxdLeA ansible",
  "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQDWodZUtB3+ks3D3i0FBZB87TUZzUcbfEY6J6GVOexGob/bN3NE7qwMFd6irWbmzmcdkhulf3RMPujW40P3pMbJlRt4lWejEXHyvoC0sSseswVOWzs7AjQQeQipd4TYRy3KilPCROICXAPgKWiNb5LHl/4Y0YrZldpUs8puoAzKzD6k0wJCyTMlTxAd2WDSonsAVlb8CoGmcJoGXipZ6rXujURNl+cRqG0NAQBK9zqu5GCDpUmH2wV49s/a5B0JTvHR4Kmkmyd/xtBulzWDSTW15F9DNJ6kQlBNLRbaup0ttgdE2ogMGwn0JrqMi6bpUVw2JjdvAREBWWPh1XDN+XmVh9Mbr1cMI11bOiLPu2lH/sApZaSvBPYfvdWAJef0L1V+jjyaUDHvcOh2RgEFWXxMSZSjpqfwY8R06NJCPFHI4cffrZqbBCLhpuRSBhWy5W40DWoc1ybpvMihbPMMzNqPrWzICYOy0aUZUv04YPxcRDd9VTV2+wKYt9Vl8f3AMuXTLsf70HCdvLItALtJU1qwgg29bL6ltxX7xtThsQG0SR+86dJWnNOSyCrFRMpgHzVyZKifGNtYwqMnYxRsUTreMg7SNl4hLXdjFAhk3dAokhS7WDXPt4uamqPfCcSVhVRSIhbPVxURz1LAh4aJ7hxe7frTHB+ABdtpBmpRmnHfYQ== openpgp:0x96508986"
]
