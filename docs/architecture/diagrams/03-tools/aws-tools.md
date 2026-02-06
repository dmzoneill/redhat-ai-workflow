# AWS Tools

> aa_aws module for Amazon Web Services management

## Diagram

```mermaid
classDiagram
    class S3Tools {
        +aws_s3_ls(path, recursive): str
        +aws_s3_cp(source, dest): str
        +aws_s3_sync(source, dest): str
        +aws_s3_rm(path, recursive): str
        +aws_s3_mb(bucket): str
        +aws_s3_rb(bucket, force): str
    }

    class EC2Tools {
        +aws_ec2_describe_instances(): str
        +aws_ec2_start_instances(ids): str
        +aws_ec2_stop_instances(ids): str
        +aws_ec2_describe_security_groups(): str
    }

    class IAMTools {
        +aws_iam_list_users(): str
        +aws_iam_list_roles(): str
        +aws_iam_get_user(username): str
    }

    class GeneralTools {
        +aws_sts_get_caller_identity(): str
        +aws_configure_list(): str
        +aws_regions_list(): str
    }
```

## Tool Categories

```mermaid
graph TB
    subgraph S3[S3 Storage]
        LS[aws_s3_ls]
        CP[aws_s3_cp]
        SYNC[aws_s3_sync]
        RM[aws_s3_rm]
        MB[aws_s3_mb]
        RB[aws_s3_rb]
    end

    subgraph EC2[Compute]
        INST[aws_ec2_describe_instances]
        START[aws_ec2_start_instances]
        STOP[aws_ec2_stop_instances]
        SG[aws_ec2_describe_security_groups]
    end

    subgraph IAM[Identity]
        USERS[aws_iam_list_users]
        ROLES[aws_iam_list_roles]
        USER[aws_iam_get_user]
    end

    subgraph Auth[Authentication]
        IDENTITY[aws_sts_get_caller_identity]
        CONFIG[aws_configure_list]
        REGIONS[aws_regions_list]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_aws/src/` | All AWS CLI tools |

## Tool Summary

### S3 Tools

| Tool | Description |
|------|-------------|
| `aws_s3_ls` | List S3 buckets or objects |
| `aws_s3_cp` | Copy files to/from S3 |
| `aws_s3_sync` | Sync directories with S3 |
| `aws_s3_rm` | Remove S3 objects |
| `aws_s3_mb` | Create S3 bucket |
| `aws_s3_rb` | Remove S3 bucket |

### EC2 Tools

| Tool | Description |
|------|-------------|
| `aws_ec2_describe_instances` | List EC2 instances |
| `aws_ec2_start_instances` | Start EC2 instances |
| `aws_ec2_stop_instances` | Stop EC2 instances |
| `aws_ec2_describe_security_groups` | List security groups |

### IAM Tools

| Tool | Description |
|------|-------------|
| `aws_iam_list_users` | List IAM users |
| `aws_iam_list_roles` | List IAM roles |
| `aws_iam_get_user` | Get IAM user details |

### General Tools

| Tool | Description |
|------|-------------|
| `aws_sts_get_caller_identity` | Get current AWS identity |
| `aws_configure_list` | Show AWS configuration |
| `aws_regions_list` | List available AWS regions |

## Usage Examples

```python
# List S3 buckets
result = await aws_s3_ls()

# Copy to S3
result = await aws_s3_cp("./data", "s3://my-bucket/data", recursive=True)

# Sync directory with S3
result = await aws_s3_sync("./uploads", "s3://my-bucket/uploads")

# List EC2 instances
result = await aws_ec2_describe_instances()

# Get current identity
result = await aws_sts_get_caller_identity()
```

## Configuration

Uses AWS CLI configuration (`~/.aws/config` and `~/.aws/credentials`). All tools support an optional `profile` parameter to use a specific AWS profile.

## Related Diagrams

- [GCloud Tools](./gcloud-tools.md)
- [Kubernetes Tools](./k8s-tools.md)
