---
name: scan-vulnerabilities
description: Scan a container image for security vulnerabilities before deployment
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: scan_vulnerabilities.yaml
  executable: "true"
---

# scan_vulnerabilities

Scan a container image for security vulnerabilities before deployment.

Uses Quay.io vulnerability scanning and optional local security tools.

Steps:
1. Verify image exists in Quay
2. Get vulnerability report from Quay
3. Analyze severity and count
4. Provide recommendations

Useful before:
- Releasing to production
- Deploying to ephemeral
- Approving MRs with image changes

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("scan_vulnerabilities", '{
  "image_tag": "example-image_tag",
  "repository": "aap-aa-tenant/aap-aa-main/automation-analytics-backend-main",
  "namespace": "redhat-user-workloads",
  "fail_on_critical": true,
  "fail_on_high": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load release persona for Quay vulnerability scanning tools**
2. **Check for known security/vulnerability issues**
3. **Get security-related gotchas from knowledge**
4. **Parse security-related gotchas**
5. **Verify the image exists in Quay**
6. **Stop if image doesn't exist**
7. **Fetch vulnerability report from Quay**
8. **Get image manifest for metadata**
9. **Parse and categorize vulnerabilities**
10. **Extract manifest metadata**
11. **Check against security policy**
12. **Search for security-related code if vulnerabilities found**
13. **Parse security code search results**
14. **Log security scan to session**
15. **Track vulnerability scans for patterns**
16. **Track CVEs that appear frequently**
17. **Update security state in memory**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `image_tag` | string | Yes | `-` | Image tag (commit SHA or version) to scan |
| `repository` | string | No | `aap-aa-tenant/aap-aa-main/automation-analytics-backend-main` | Quay repository path |
| `namespace` | string | No | `redhat-user-workloads` | Quay namespace (redhat-user-workloads for PR, redhat-services-prod for releases) |
| `fail_on_critical` | boolean | No | `true` | Return error if critical vulnerabilities found |
| `fail_on_high` | boolean | No | `false` | Return error if high severity vulnerabilities found |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the scan_vulnerabilities skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("scan_vulnerabilities", '{
  "image_tag": "example-image_tag",
  "repository": "aap-aa-tenant/aap-aa-main/automation-analytics-backend-main",
  "namespace": "redhat-user-workloads",
  "fail_on_critical": true,
  "fail_on_high": false
}')
```

### Via Command (if configured)

```
/scan-vulnerabilities
```

## MCP Tools Used

- `code_search`
- `knowledge_query`
- `memory_session_log`
- `persona_load`
- `quay_check_image_exists`
- `quay_get_manifest`
- `quay_get_vulnerabilities`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/scan_vulnerabilities.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/scan_vulnerabilities.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
