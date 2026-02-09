# Vm Lab Setup

Create and manage local virtual machines for testing environments.

## Instructions

```text
skill_run("vm_lab_setup", '{"action": "$ACTION", "vm_name": "$VM_NAME", "base_image": "", "memory_mb": "", "vcpus": ""}')
```

## What It Does

Create and manage local virtual machines for testing environments.

This skill handles:
- Creating new VMs from base images
- Cloning existing VMs
- Creating and reverting snapshots
- Destroying VMs
- Checking VM status and resource info

Uses: virsh_list, virsh_start, virsh_shutdown, virsh_destroy, virsh_reboot,
virt_install, virsh_clone, virsh_dominfo, virsh_domstate, virsh_domblklist,
virsh_domiflist, virsh_dumpxml, virsh_vcpuinfo, virsh_memtune,
virsh_snapshot_create, virsh_snapshot_list, virsh_snapshot_revert,
virsh_snapshot_delete, virsh_pool_list, virsh_pool_info, virsh_vol_list,
virsh_net_list, virsh_net_info, ssh_test, ssh_command, ssh_keyscan,
ansible_ping

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `action` | Action to perform (create|clone|snapshot|revert|destroy|status) | Yes |
| `vm_name` | Name of the virtual machine | Yes |
| `base_image` | Path to base image for VM creation | No |
| `memory_mb` | Memory allocation in MB (default: 2048) | No |
| `vcpus` | Number of virtual CPUs (default: 2) | No |
