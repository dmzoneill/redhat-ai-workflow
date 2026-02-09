---
name: vm-network-setup
description: "Configure and manage virtual networking for libvirt VMs."
arguments:
  - name: action
    required: true
  - name: network_name
  - name: bridge
---
# Vm Network Setup

Configure and manage virtual networking for libvirt VMs.

## Instructions

```text
skill_run("vm_network_setup", '{"action": "$ACTION", "network_name": "", "bridge": ""}')
```

## What It Does

Configure and manage virtual networking for libvirt VMs.

This skill handles:
- Listing virtual networks and their status
- Creating and starting virtual networks
- Stopping and destroying virtual networks
- Inspecting network configurations
- Scanning for active hosts on networks
- Managing VM network interfaces
- Defining network XML configurations

Uses: virsh_net_list, virsh_net_info, virsh_net_start, virsh_net_destroy,
virsh_domiflist, virsh_list, virsh_dumpxml, virsh_define,
nmap_ping_scan, ssh_test

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `action` | Action to perform (list|create|start|stop|scan) | Yes |
| `network_name` | Name of the virtual network (default: default) | No |
| `bridge` | Bridge interface name | No |
