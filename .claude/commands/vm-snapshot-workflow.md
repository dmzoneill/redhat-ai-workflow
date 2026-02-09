---
name: vm-snapshot-workflow
description: "Manage VM snapshot lifecycle including creation, revert, and cleanup."
arguments:
  - name: vm_name
    required: true
  - name: action
    required: true
  - name: snapshot_name
---
# Vm Snapshot Workflow

Manage VM snapshot lifecycle including creation, revert, and cleanup.

## Instructions

```text
skill_run("vm_snapshot_workflow", '{"vm_name": "$VM_NAME", "action": "$ACTION", "snapshot_name": ""}')
```

## What It Does

Manage VM snapshot lifecycle including creation, revert, and cleanup.

This skill handles:
- Creating named snapshots of running VMs
- Listing and inspecting existing snapshots
- Reverting VMs to previous snapshots
- Cleaning up old snapshots
- Suspending/resuming VMs for consistent snapshots
- Managing storage volumes

Uses: virsh_list, virsh_domstate, virsh_dominfo, virsh_snapshot_create,
virsh_snapshot_list, virsh_snapshot_revert, virsh_snapshot_delete,
virsh_suspend, virsh_resume, virsh_vol_list, virsh_vol_resize,
virsh_vol_delete, virsh_pool_info, virsh_vcpuinfo, virsh_memtune

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `vm_name` | Name of the virtual machine | Yes |
| `action` | Action to perform (create|revert|commit|list|cleanup) | Yes |
| `snapshot_name` | Name of the snapshot | No |
