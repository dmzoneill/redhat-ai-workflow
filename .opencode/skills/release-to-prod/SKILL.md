---
name: release-to-prod
description: Create a Konflux release to push images from staging to production
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: release_to_prod.yaml
  executable: "true"
---

# release_to_prod

Create a Konflux release to push images from staging to production.

This skill handles the full release workflow:
1. Verify the image exists in staging (redhat-user-workloads)
2. Check current release status in Konflux
3. Get component information
4. Create the release to production
5. Monitor release status

Prerequisites:
- Image must be built and available in Quay staging
- User must have Konflux access

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("release_to_prod", '{
  "commit_sha": "example-commit_sha",
  "component": "automation-analytics-backend-main",
  "namespace": "aap-aa-tenant",
  "application": "aap-aa-main",
  "dry_run": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load release persona for Konflux release tools**
2. **Get release gotchas from knowledge**
3. **Parse release-related gotchas**
4. **Check for known release issues**
5. **Search codebase for changes related to this release**
6. **Parse code search results for release context**
7. **Validate commit SHA format**
8. **Verify image exists in staging Quay**
9. **Parse staging image check result**
10. **Scan image for security vulnerabilities (uses scan_vulnerabilities skill)**
11. **Parse vulnerability scan skill result**
12. **Get Konflux component details**
13. **List all components in application**
14. **Parse component information**
15. **List recent releases**
16. **Get details of latest release**
17. **Parse release information**
18. **Validate app-interface configuration before release**
19. **Parse validation result**
20. **Create Konflux release**
21. **Parse release creation result**
22. **Log release to session**
23. **Save release to history for tracking**
24. **Mark release on Grafana dashboards**
25. **Announce release to team channel (uses notify_team skill)**
26. **Detect failure patterns from release operations**
27. **Learn from staging image not found failures**
28. **Learn from Konflux auth failures**
29. **Learn from Konflux VPN failures**
30. **Learn from release already exists failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `commit_sha` | string | Yes | `-` | Git commit SHA to release (40-char full SHA) |
| `component` | string | No | `automation-analytics-backend-main` | Konflux component name |
| `namespace` | string | No | `aap-aa-tenant` | Konflux tenant namespace |
| `application` | string | No | `aap-aa-main` | Konflux application name |
| `dry_run` | boolean | No | `false` | If true, just show what would be released without creating |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the release_to_prod skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("release_to_prod", '{
  "commit_sha": "example-commit_sha",
  "component": "automation-analytics-backend-main",
  "namespace": "aap-aa-tenant",
  "application": "aap-aa-main",
  "dry_run": false
}')
```

### Via Command (if configured)

```
/release-to-prod
```

## MCP Tools Used

- `appinterface_validate`
- `code_search`
- `grafana_annotation_create`
- `knowledge_query`
- `konflux_create_release`
- `konflux_get_component`
- `konflux_get_release`
- `konflux_list_components`
- `konflux_list_releases`
- `learn_tool_fix`
- `memory_append`
- `memory_session_log`
- `persona_load`
- `quay_check_image_exists`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/release_to_prod.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/release_to_prod.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
