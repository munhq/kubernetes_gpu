# Base Role

Base system configuration applied to all hosts in the inventory.

## Purpose

Provides foundational OS-level setup that every machine needs:
- Essential packages (curl, wget, git, vim, htop, jq, etc.)
- Timezone configuration
- For K8s nodes: kernel modules, sysctl tuning, ulimits, journald config

## Variables

See `group_vars/all.yml` and `group_vars/k3s_cluster.yml` for configurable variables.

## Usage

Applied automatically via `infrastructure.yml` playbook to all hosts in `k3s_cluster` group.

```yaml
- hosts: k3s_cluster
  roles:
    - base
```
