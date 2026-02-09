# Cloud Inventory

Get a comprehensive inventory of cloud resources across AWS and GCP.

## Instructions

```text
skill_run("cloud_inventory", '{"providers": "", "include_iam": "", "include_storage": ""}')
```

## What It Does

Get a comprehensive inventory of cloud resources across AWS and GCP.

This skill discovers:
- AWS EC2 instances and security groups
- AWS S3 buckets
- AWS IAM users and roles
- GCP projects and compute instances
- GCP storage buckets
- GCP GKE clusters

Uses: aws_sts_get_caller_identity, aws_configure_list,
aws_ec2_describe_instances, aws_ec2_describe_security_groups,
aws_s3_ls, aws_iam_list_users, aws_iam_list_roles,
aws_regions_list, gcloud_auth_list, gcloud_config_list,
gcloud_projects_list, gcloud_compute_instances_list,
gcloud_storage_ls, gcloud_container_clusters_list

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `providers` | Cloud providers to inventory (aws, gcp, all) (default: all) | No |
| `include_iam` | Include IAM users and roles inventory | No |
| `include_storage` | Include storage (S3/GCS) inventory (default: True) | No |
