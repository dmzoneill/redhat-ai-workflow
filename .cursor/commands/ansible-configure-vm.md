# Ansible Configure Vm

Configure virtual machines using Ansible playbooks and ad-hoc commands.

## Instructions

```text
skill_run("ansible_configure_vm", '{"playbook": "", "inventory": "", "hosts": "", "tags": "", "check_mode": "", "install_requirements": ""}')
```

## What It Does

Configure virtual machines using Ansible playbooks and ad-hoc commands.

This skill handles:
- Running Ansible playbooks against VMs
- Installing Galaxy roles/collections
- Ad-hoc module execution
- Inventory and host management
- Dry-run with check mode

Uses: ansible_inventory_list, ansible_inventory_graph, ansible_inventory_host,
ansible_ping, ansible_setup, ansible_playbook_check, ansible_playbook_run,
ansible_playbook_list_tasks, ansible_playbook_list_tags,
ansible_galaxy_search, ansible_galaxy_install, ansible_galaxy_list,
ansible_galaxy_remove, ansible_config_dump, ansible_version,
ansible_command, ansible_shell, ansible_copy, ansible_fetch, ssh_test

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `playbook` | Path to Ansible playbook to run | No |
| `inventory` | Path to inventory file (default: inventory.yaml) | No |
| `hosts` | Target hosts or group pattern (default: all) | No |
| `tags` | Ansible tags to run | No |
| `check_mode` | Run in check (dry-run) mode | No |
| `install_requirements` | Install Galaxy requirements before running | No |
