---
name: remote-host-diagnostics
description: "Diagnose remote host health via SSH, Ansible, and network scanning."
arguments:
  - name: host
    required: true
  - name: user
  - name: commands
  - name: gather_facts
  - name: fetch_logs
---
# Remote Host Diagnostics

Diagnose remote host health via SSH, Ansible, and network scanning.

## Instructions

```text
skill_run("remote_host_diagnostics", '{"host": "$HOST", "user": "", "commands": "", "gather_facts": "", "fetch_logs": ""}')
```

## What It Does

Diagnose remote host health via SSH, Ansible, and network scanning.

This skill handles:
- SSH connectivity testing
- Remote command execution
- Ansible fact gathering
- Network scanning and service discovery
- SSH configuration review
- Log retrieval from remote hosts

Uses: ssh_test, ssh_command, ssh_config_list, ssh_known_hosts_list,
ssh_add_list, ssh_fingerprint, ansible_setup, ansible_command,
ansible_shell, ansible_fetch, nmap_ping_scan, nmap_service_scan

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `host` | Target host to diagnose | Yes |
| `user` | SSH username | No |
| `commands` | Commands to run on the remote host (default: hostname && uptime && free -h && df -h) | No |
| `gather_facts` | Gather Ansible facts from the host (default: True) | No |
| `fetch_logs` | Fetch system logs from remote host | No |
