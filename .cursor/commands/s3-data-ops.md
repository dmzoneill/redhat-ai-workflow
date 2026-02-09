# S3 Data Ops

Perform S3 data operations including listing, uploading, downloading,

## Instructions

```text
skill_run("s3_data_ops", '{"action": "$ACTION", "bucket": "", "path": "", "pattern": ""}')
```

## What It Does

Perform S3 data operations including listing, uploading, downloading,
syncing, and cleanup of S3 buckets and objects.

This skill supports:
- Listing buckets and objects
- Uploading and downloading files
- Syncing directories to/from S3
- Bucket creation and removal
- EC2 instance management for data processing
- Downloading files via HTTP

Uses: aws_sts_get_caller_identity, aws_s3_ls, aws_s3_cp, aws_s3_sync,
aws_s3_rm, aws_s3_mb, aws_s3_rb, aws_ec2_start_instances,
aws_ec2_stop_instances, aws_iam_get_user, curl_download

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `action` | Action to perform (ls, upload, download, sync, cleanup) | Yes |
| `bucket` | S3 bucket name (e.g., my-bucket) | No |
| `path` | S3 key path or local file path | No |
| `pattern` | File pattern for filtering (e.g., *.csv) | No |
