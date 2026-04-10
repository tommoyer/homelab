# Kanidm Debian Ansible Role

This archive bootstraps Debian-based systems for Kanidm authentication using PAM/NSS,
SSH public key lookup through `kanidm_ssh_authorizedkeys`, and sudo access via the
Kanidm POSIX group `linux-admins`.

## Included defaults

- Kanidm URL: `https://kanidm.moyer.wtf`
- Login group: `linux-users`
- Sudo group: `linux-admins`
- SSH key lookup mode: cached `kanidm_ssh_authorizedkeys`
- CA certificate source: `roles/kanidm_client/files/kanidm-ca.crt`

## Before running

1. Replace `roles/kanidm_client/files/kanidm-ca.crt` with your real CA certificate.
2. Add your Debian hosts to `inventory/hosts` under the `kanidm-linux-login` group, or have your dynamic inventory generator emit that group.
3. Review `group_vars/debian_kanidm.yml` for overrides.
4. If anonymous Kanidm read access is disabled, set:
   - `kanidm_service_account_enabled: true`
   - `kanidm_service_account_token: "...token..."`

## Run

```bash
ansible-playbook -i inventory/hosts playbooks/kanidm-debian.yml
```

## Verify on a client

```bash
getent passwd youruser
getent group linux-users
getent group linux-admins
kanidm-unix status
kanidm_ssh_authorizedkeys youruser
sudo -l -U youruser
```
