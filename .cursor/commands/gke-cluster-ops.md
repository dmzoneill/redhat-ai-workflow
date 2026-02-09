# Gke Cluster Ops

Manage GKE clusters and GCP compute resources.

## Instructions

```text
skill_run("gke_cluster_ops", '{"action": "$ACTION", "project": "", "cluster": ""}')
```

## What It Does

Manage GKE clusters and GCP compute resources.

This skill supports:
- Listing clusters and compute instances
- Starting and stopping instances
- Inspecting instance details
- GCS storage operations
- Authentication and project management

Uses: gcloud_auth_list, gcloud_config_list, gcloud_config_set_project,
gcloud_projects_list, gcloud_compute_instances_list,
gcloud_compute_instances_start, gcloud_compute_instances_stop,
gcloud_compute_instances_describe, gcloud_container_clusters_list,
gcloud_storage_ls, gcloud_storage_cp, gcloud_storage_rm

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `action` | Action to perform (list, start, stop, credentials, storage) | Yes |
| `project` | GCP project ID | No |
| `cluster` | GKE cluster name | No |
