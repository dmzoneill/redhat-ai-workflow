---
name: scan-vulns
description: "Check container image for security vulnerabilities."
arguments:
  - name: image
    required: true
---
# Scan Vulnerabilities

Check container image for security vulnerabilities.

## Instructions

```
skill_run("scan_vulnerabilities", '{"image": "$IMAGE"}')
```

## What It Does

1. Verifies image exists in Quay
2. Retrieves vulnerability scan results
3. Categorizes by severity (Critical/High/Medium/Low)
4. Lists CVEs with details

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image` | Full image path | Required |
| `tag` | Image tag or SHA | `latest` |

## Examples

```bash
# Scan latest
skill_run("scan_vulnerabilities", '{"image": "quay.io/cloudservices/automation-analytics-api"}')

# Scan specific tag
skill_run("scan_vulnerabilities", '{"image": "quay.io/cloudservices/automation-analytics-api", "tag": "abc1234"}')
```

## Integration

This is automatically run in `/release-prod` as a security gate.




