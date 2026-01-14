# /scan-vulns

> Check container image for security vulnerabilities.

## Overview

Check container image for security vulnerabilities.

**Underlying Skill:** `scan_vulnerabilities`

This command is a wrapper that calls the `scan_vulnerabilities` skill. For detailed process information, see [skills/scan_vulnerabilities.md](../skills/scan_vulnerabilities.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `image` | No | - |

## Usage

### Examples

```bash
skill_run("scan_vulnerabilities", '{"image": "$IMAGE"}')
```

```bash
# Scan latest
skill_run("scan_vulnerabilities", '{"image": "quay.io/cloudservices/automation-analytics-api"}')

# Scan specific tag
skill_run("scan_vulnerabilities", '{"image": "quay.io/cloudservices/automation-analytics-api", "tag": "abc1234"}')
```

## Process Flow

This command invokes the `scan_vulnerabilities` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /scan-vulns]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call scan_vulnerabilities skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [scan_vulnerabilities skill documentation](../skills/scan_vulnerabilities.md).

## Details

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


## Related Commands

_(To be determined based on command relationships)_
