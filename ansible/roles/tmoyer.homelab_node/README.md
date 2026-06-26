# tmoyer.homelab_node

Composite role for bootstrapping and configuring homelab Linux nodes.

This role can run bootstrap tasks as `root` only, then reconnect and continue as your normal Ansible user.

## What this role can manage

- ansible user and SSH bootstrap setup
- apt-cacher-ng client config
- base hardening
- Kanidm client integration
- node_exporter install + service

## Key variables

### Feature flags

```yaml
homelab_node_bootstrap_enabled: false
homelab_node_apt_cacher_ng_enabled: false
homelab_node_hardening_enabled: true
homelab_node_kanidm_enabled: false
homelab_node_node_exporter_enabled: true
```

### Bootstrap connection control

```yaml
homelab_node_bootstrap_remote_user: root
homelab_node_reset_connection_after_bootstrap: true
homelab_ansible_user: ansible
homelab_ansible_home: /home/ansible
homelab_ansible_ssh_pubkey_path: "~/.ssh/ansible.pub"
```

When bootstrap is enabled, the role applies `remote_user` only to bootstrap tasks, then runs `meta: reset_connection` so later tasks reconnect using your normal connection settings.

## Recommended pattern for brand-new hosts

Use a play that starts as `root` and does **not** gather facts first. This avoids early failures before the `ansible` user exists.

```yaml
---
- name: Bootstrap and configure new nodes
  hosts: new_nodes
  gather_facts: false
  remote_user: root
  become: true

  roles:
    - role: tmoyer.homelab_node
      vars:
        homelab_node_bootstrap_enabled: true
        homelab_node_hardening_enabled: true
        homelab_node_node_exporter_enabled: true
        homelab_node_bootstrap_remote_user: root
        homelab_node_reset_connection_after_bootstrap: true

  post_tasks:
    - name: Switch connection user to ansible after bootstrap
      ansible.builtin.set_fact:
        ansible_user: "{{ homelab_ansible_user }}"

    - name: Reconnect using ansible user
      ansible.builtin.meta: reset_connection

    - name: Gather facts after bootstrap user switch
      ansible.builtin.setup:
```

## Typical pattern for already-managed hosts

If hosts are already reachable as your normal user (for example `ansible` from `ansible.cfg`), leave bootstrap disabled and enable only the features you want.

```yaml
---
- name: Configure existing nodes
  hosts: existing_nodes
  gather_facts: true
  become: true

  roles:
    - role: tmoyer.homelab_node
      vars:
        homelab_node_bootstrap_enabled: false
        homelab_node_hardening_enabled: true
        homelab_node_node_exporter_enabled: true
```
