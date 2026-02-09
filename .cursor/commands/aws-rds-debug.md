# Aws Rds Debug

Debug AWS RDS database issues by gathering infrastructure and

## Instructions

```text
skill_run("aws_rds_debug", '{"environment": "", "issue_description": "", "check_connections": ""}')
```

## What It Does

Debug AWS RDS database issues by gathering infrastructure and
database-level diagnostics.

This skill inspects:
- AWS identity and configuration
- EC2 instances and security groups for RDS access
- PostgreSQL connection health, locks, and activity
- Database size and connection count
- InScope documentation for RDS configuration guidance

Uses: aws_sts_get_caller_identity, aws_configure_list,
aws_ec2_describe_instances, aws_ec2_describe_security_groups,
psql_query, psql_activity, psql_locks, psql_size,
psql_connections, curl_get, ssh_command, inscope_query

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `environment` | Environment (stage, production) (default: stage) | No |
| `issue_description` | Description of the RDS issue to investigate | No |
| `check_connections` | Include connection and lock analysis (default: True) | No |
