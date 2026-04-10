#!/bin/bash

kanidm group create proxmox_users

kanidm system oauth2 create proxmox Proxmox https://proxmox.moyer.wtf
kanidm system oauth2 add-redirect-url proxmox https://proxmox.moyer.wtf
kanidm system oauth2 update-scope-map proxmox proxmox_users openid email profile groups

kanidm group add-members proxmox_users tmoyer

kanidm system oauth2 show-basic-secret proxmox
