---
name: test-mr-ephemeral
description: Deploy an MR's image to an ephemeral namespace for testing
license: MIT
compatibility: opencode
metadata:
  version: "1.4"
  source: test_mr_ephemeral.yaml
  executable: "true"
---

# test_mr_ephemeral

Deploy an MR's image to an ephemeral namespace for testing.

## How It Works
1. Gets commit SHA from MR (via GitLab MCP)
2. Checks if Konflux has built the image (via Quay MCP) - STOPS if not ready
3. Reserves ephemeral namespace (via bonfire MCP)
4. Deploys using full SHA image tag (via bonfire_deploy_aa)
5. Runs pytest against ephemeral DB (optional)

## Prerequisites
- Konflux must have built the image (check quay.io/redhat-user-workloads/aap-aa-tenant)
- User must be logged into ephemeral cluster (run `kube e` once)

## NEVER Do These Things
- DO NOT copy kubeconfig files (cp ~/.kube/config.e ~/.kube/config)
- DO NOT run raw `bonfire deploy` without --set-image-tag with FULL SHA
- DO NOT use short SHA (8 chars like 8d23cab) - images are tagged with FULL 40-char SHA
- DO NOT truncate the SHA - Quay only has images tagged with full 40-char commit SHA

## Why Full SHA Matters
Konflux tags images with the FULL 40-char git commit SHA, not short form.
- WRONG: quay.io/.../image:8d23cab (manifest unknown!)
- RIGHT: quay.io/.../image:8d23cab1234567890abcdef1234567890abcdef12

## Key Config Values (from config.json)
- App: tower-analytics
- Component: tower-analytics-clowdapp (main) or tower-analytics-billing-clowdapp (billing)
- Image base: quay.io/redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main

## ITS Deploy Pattern (what bonfire needs)
- template_ref: Full 40-char git commit SHA
- IMAGE: quay.io/.../image@sha256 (base + @sha256 suffix)
- IMAGE_TAG: 64-char sha256 digest from Quay (NOT the git SHA!)

The skill automatically extracts the sha256 digest from Quay after checking the image exists.

## STOP Conditions
- If image not in Quay: STOP, tell user to wait for Konflux build
- If namespace reservation fails: STOP, check cluster login

DO NOT fall back to raw bonfire commands - always use the MCP tools.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("test_mr_ephemeral", '{
  "mr_id": "example-mr_id",
  "commit_sha": "example-commit_sha",
  "duration": "2h",
  "run_tests": true,
  "billing": None,
  "cleanup_on_failure": true,
  "cleanup_on_success": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load Konflux, Quay, and GitLab configuration**
2. **Verify bonfire and kubectl are available**
3. **Load developer persona for GitLab, Git, and Jira operations**
4. **Get full 40-char commit SHA from GitLab MR**
5. **Extract SHA from gitlab_mr_sha response**
6. **Check GitLab CI pipeline status for MR**
7. **Parse GitLab CI status**
8. **resolve_commit**
9. **validate_commit**
10. **Get commit message for Jira key extraction**
11. **Extract Jira key and billing keywords from commit using shared parser**
12. **Look for billing indicators in Jira issue**
13. **Check if Jira issue mentions billing**
14. **Get list of files changed in this commit**
15. **Check if commit modifies billing-related files**
16. **Decide whether to deploy billing or main ClowdApp**
17. **Verify the image was built and get sha256 digest for bonfire**
18. **Load release persona for Konflux and Tekton operations**
19. **Check Konflux build status for this commit**
20. **List Tekton pipeline runs to find this commit's build**
21. **List recent snapshots to find deployment candidate**
22. **Get snapshot details for this commit**
23. **Find pipeline run for this specific commit**
24. **Get detailed status of the pipeline run**
25. **Extract detailed pipeline information**
26. **Get Tekton pipeline run logs**
27. **Get logs from failed build**
28. **Parse build failure details from Konflux and Tekton logs**
29. **validate_image**
30. **STOP if image not built yet**
31. **Load devops persona for Bonfire and Kubernetes operations**
32. **Reserve an ephemeral namespace**
33. **get_namespace_name**
34. **Deploy AA to ephemeral namespace using {{ clowdapp_selection.clowdapp }}**
35. **Wait for deployment to be ready**
36. **Get Kubernetes events for deployment troubleshooting**
37. **Parse deployment events for issues**
38. **Get DB host from secret**
39. **Get DB port from secret**
40. **Get DB user from secret**
41. **Get DB password from secret**
42. **Get DB name from secret**
43. **Build DB credentials object from secret values**
44. **Get pod status in namespace**
45. **Identify any failing pods for detailed diagnosis**
46. **Get detailed info on first failing pod**
47. **Parse pod description for issue details**
48. **Get all pods in namespace**
49. **Find the FastAPI pod from pod listing**
50. **Create smoke test script with DB credentials**
51. **Copy smoke test script to FastAPI pod**
52. **Execute smoke tests in FastAPI pod**
53. **Parse smoke test output**
54. **Release namespace if deployment or tests failed**
55. **Release namespace after successful tests**
56. **Report cleanup status**
57. **Notify about ephemeral environment status**
58. **Notify team channel about ephemeral environment ready**
59. **Notify team channel about test failures in ephemeral**
60. **Find test files related to the changed code**
61. **Parse related test results**
62. **Get testing-specific gotchas from knowledge**
63. **Parse testing gotchas**
64. **Check for known ephemeral/bonfire issues**
65. **Build context for memory updates**
66. **Log ephemeral deployment to session**
67. **Track ephemeral namespace in environment memory**
68. **Detect failure patterns from tool outputs**
69. **Learn from GitLab failures**
70. **Learn from Quay manifest unknown failures**
71. **Learn from bonfire pool exhaustion**
72. **Learn from Kubernetes auth failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mr_id` | integer | No | `-` | GitLab MR ID (will find the image from Konflux) |
| `commit_sha` | string | No | `-` | Specific commit SHA to test (alternative to mr_id) |
| `duration` | string | No | `2h` | How long to reserve namespace (e.g., 1h, 2h, 4h) |
| `run_tests` | boolean | No | `true` | Run pytest against ephemeral environment |
| `billing` | boolean | No | `None` | Which ClowdApp to deploy: - null (default): AUTO-DETECT from Jira issue and commit diff - false: Force tower-analytics-clowdapp (main app) - true: Force tower-analytics-billing-clowdapp (billing features)  Auto-detection checks: 1. Jira issue key in commit → search for "billing" in issue 2. Commit modifies aap_billing_controller/ files 3. Commit modifies test/processor/aap_billing_controller/ files  |
| `cleanup_on_failure` | boolean | No | `true` | Release namespace if deployment/tests fail |
| `cleanup_on_success` | boolean | No | `false` | Release namespace after successful tests (default: keep for manual testing) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the test_mr_ephemeral skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("test_mr_ephemeral", '{
  "mr_id": "example-mr_id",
  "commit_sha": "example-commit_sha",
  "duration": "2h",
  "run_tests": true,
  "billing": None,
  "cleanup_on_failure": true,
  "cleanup_on_success": false
}')
```

### Via Command (if configured)

```
/test-mr-ephemeral
```

## MCP Tools Used

- `bonfire_deploy_aa`
- `bonfire_namespace_release`
- `bonfire_namespace_reserve`
- `bonfire_namespace_wait`
- `code_search`
- `git_diff_tree`
- `git_show`
- `gitlab_ci_status`
- `gitlab_mr_sha`
- `jira_get_issue`
- `knowledge_query`
- `konflux_get_build_logs`
- `konflux_get_snapshot`
- `konflux_list_builds`
- `konflux_list_snapshots`
- `kubectl_cp`
- `kubectl_describe_pod`
- `kubectl_exec`
- `kubectl_get_events`
- `kubectl_get_pods`
- `kubectl_get_secret_value`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`
- `skill_run`
- `skopeo_get_digest`
- `tkn_pipelinerun_describe`
- `tkn_pipelinerun_list`
- `tkn_pipelinerun_logs`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/test_mr_ephemeral.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/test_mr_ephemeral.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
