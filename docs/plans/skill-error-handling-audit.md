# Skill Error Handling Audit

## Overview

This document tracks the analysis of each skill's error handling strategy.
Goal: Replace blind `on_error: continue` with smarter approaches:

1. **auto_heal** - Try kube_login/vpn_connect, retry, then continue
2. **memory_lookup** - Check memory for known fixes before failing
3. **vector_search** - Search for similar past errors and their solutions
4. **fail_fast** - Critical steps that should stop the skill
5. **continue** - Optional enrichment that's OK to skip

## Error Handling Decision Tree

```
Is this step CRITICAL to the skill's purpose?
├── YES → Should it auto-heal?
│   ├── YES (k8s/network/auth error likely) → on_error: auto_heal
│   └── NO (data validation, business logic) → on_error: fail
└── NO (optional enrichment)
    ├── Can we get value from memory/cache? → Add memory_read fallback
    ├── Is this expensive to retry? → on_error: continue
    └── Is this cheap and might work later? → on_error: auto_heal
```

---

## Priority 1: Core Infrastructure Skills

### test_mr_ephemeral.yaml (46 on_error: continue)

**Purpose:** Deploy MR to ephemeral namespace for testing

| Step | Current | Recommended | Reason |
|------|---------|-------------|--------|
| `get_mr_sha` | continue | **auto_heal** | GitLab API - auth issues common |
| `check_gitlab_ci` | continue | **auto_heal** | GitLab API |
| `parse_gitlab_ci` | continue | continue | Compute step, no external call |
| `get_commit_message` | continue | continue | Local git, fast |
| `check_jira_billing` | continue | **auto_heal** | Jira API - auth issues |
| `get_changed_files` | continue | continue | Local git, fast |
| `check_quay_image` | continue | **auto_heal** | Quay API - critical for deploy |
| `list_tekton_pipelines` | continue | **auto_heal** | Konflux cluster - auth issues |
| `list_snapshots` | continue | **auto_heal** | Konflux cluster |
| `get_snapshot_for_sha` | continue | **auto_heal** | Konflux cluster |
| `describe_pipeline_run` | continue | **auto_heal** | Konflux cluster |
| `get_tekton_logs` | continue | **auto_heal** | Konflux cluster |
| `get_build_logs` | continue | **auto_heal** | Konflux cluster |
| `bonfire_namespace_reserve` | continue | **auto_heal** | CRITICAL - ephemeral cluster auth |
| `wait_for_ready` | continue | **auto_heal** | Ephemeral cluster |
| `get_deployment_events` | continue | **auto_heal** | Ephemeral cluster |
| `kubectl_get_secret_value` (x5) | continue | **auto_heal** | Ephemeral cluster - DB secrets |
| `check_pods` | continue | **auto_heal** | Ephemeral cluster |
| `describe_failing_pod` | continue | **auto_heal** | Ephemeral cluster |
| `get_all_pods` | continue | **auto_heal** | Ephemeral cluster |

**Memory opportunities:**
- Cache last successful namespace reservation pool
- Store common failure patterns and their fixes
- Remember which MRs were recently tested

**Vector search opportunities:**
- Search for similar deployment failures
- Find related Jira issues with same error patterns

---

### deploy_to_ephemeral.yaml

**Purpose:** Deploy to ephemeral without running tests

Similar to test_mr_ephemeral but simpler. Apply same patterns.

---

### debug_prod.yaml (50 on_error: continue)

**Purpose:** Debug production issues

| Step | Current | Recommended | Reason |
|------|---------|-------------|--------|
| `kubectl_get_pods` | continue | **auto_heal** | Prod cluster auth |
| `kubectl_logs` | continue | **auto_heal** | Prod cluster auth |
| `prometheus_query` | continue | **auto_heal** | Prometheus auth |
| `kibana_search_logs` | continue | **auto_heal** | Kibana auth (may need manual) |
| `alertmanager_alerts` | continue | **auto_heal** | Alertmanager auth |

**Memory opportunities:**
- Store common error patterns and their root causes
- Cache recent alerts and their resolutions
- Remember which pods were problematic recently

---

### investigate_alert.yaml (31 on_error: continue)

**Purpose:** Investigate production alerts

| Step | Current | Recommended | Reason |
|------|---------|-------------|--------|
| `alertmanager_get_alert` | continue | **auto_heal** | Alertmanager auth |
| `prometheus_query` | continue | **auto_heal** | Prometheus auth |
| `kubectl_get_pods` | continue | **auto_heal** | Cluster auth |
| `kibana_search_logs` | continue | **auto_heal** | Kibana auth |
| `memory_read` | continue | continue | Memory is optional enrichment |
| `knowledge_query` | continue | continue | Knowledge is optional enrichment |

**Memory opportunities:**
- Store alert → root cause mappings
- Remember which alerts were false positives
- Cache runbook steps for common alerts

---

## Priority 2: Development Workflow Skills

### start_work.yaml (36 on_error: continue)

**Purpose:** Start work on a Jira issue

| Step | Current | Recommended | Reason |
|------|---------|-------------|--------|
| `git_status` | continue | continue | Local git, fast |
| `jira_view_issue` | continue | **auto_heal** | Jira API auth |
| `code_search` | continue | continue | Optional enrichment |
| `knowledge_query` | continue | continue | Optional enrichment |
| `git_fetch` | continue | **auto_heal** | Git remote auth |
| `git_branch_create` | continue | continue | Local git |

**Memory opportunities:**
- Cache Jira issue details for offline access
- Store related code patterns for this issue type
- Remember branch naming conventions

---

### create_mr.yaml (36 on_error: continue)

**Purpose:** Create a merge request

| Step | Current | Recommended | Reason |
|------|---------|-------------|--------|
| `git_status` | continue | continue | Local git |
| `git_push` | continue | **auto_heal** | Git remote auth |
| `gitlab_mr_create` | continue | **auto_heal** | GitLab API auth |
| `jira_set_status` | continue | **auto_heal** | Jira API auth |
| `memory_session_log` | continue | continue | Optional logging |

---

### review_pr.yaml (55 on_error: continue)

**Purpose:** Review a pull request

| Step | Current | Recommended | Reason |
|------|---------|-------------|--------|
| `gitlab_mr_view` | continue | **auto_heal** | GitLab API auth |
| `gitlab_mr_diff` | continue | **auto_heal** | GitLab API auth |
| `code_search` | continue | continue | Optional enrichment |
| `knowledge_query` | continue | continue | Optional enrichment |

**Memory opportunities:**
- Cache MR details for offline review
- Store review patterns and common issues
- Remember reviewer preferences

---

## Priority 3: Operational Skills

### rollout_restart.yaml

| Step | Current | Recommended | Reason |
|------|---------|-------------|--------|
| `kubectl_rollout_restart` | continue | **auto_heal** | Cluster auth - CRITICAL |
| `kubectl_get_pods` | continue | **auto_heal** | Cluster auth |

---

### scale_deployment.yaml

| Step | Current | Recommended | Reason |
|------|---------|-------------|--------|
| `kubectl_scale` | continue | **auto_heal** | Cluster auth - CRITICAL |
| `kubectl_get_deployments` | continue | **auto_heal** | Cluster auth |

---

### silence_alert.yaml

| Step | Current | Recommended | Reason |
|------|---------|-------------|--------|
| `alertmanager_silence` | continue | **auto_heal** | Alertmanager auth - CRITICAL |

---

## Priority 4: Utility Skills (Keep as continue)

These skills are mostly optional enrichment and should keep `on_error: continue`:

- `beer.yaml` - Fun skill, non-critical
- `coffee.yaml` - Fun skill, non-critical
- `memory_*.yaml` - Memory operations, already handle errors
- `learn_*.yaml` - Learning operations, non-critical
- `knowledge_*.yaml` - Knowledge operations, non-critical

---

## Implementation Plan

### Phase 1: Critical Infrastructure (Week 1)
1. [ ] test_mr_ephemeral.yaml - Convert k8s/API calls to auto_heal
2. [ ] deploy_to_ephemeral.yaml - Same pattern
3. [ ] debug_prod.yaml - Convert monitoring calls to auto_heal

### Phase 2: Development Workflow (Week 2)
4. [ ] start_work.yaml - Convert Jira/GitLab calls to auto_heal
5. [ ] create_mr.yaml - Convert git push/GitLab calls to auto_heal
6. [ ] review_pr.yaml - Convert GitLab calls to auto_heal

### Phase 3: Operational Skills (Week 3)
7. [ ] rollout_restart.yaml - Convert kubectl calls to auto_heal
8. [ ] scale_deployment.yaml - Convert kubectl calls to auto_heal
9. [ ] investigate_alert.yaml - Convert monitoring calls to auto_heal

### Phase 4: Memory Integration (Week 4)
10. [ ] Add memory_read fallbacks for cached data
11. [ ] Add memory_write for successful patterns
12. [ ] Add vector search for similar errors

---

## Metrics to Track

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| Skills with auto_heal | 0 | **172** ✅ | 20+ |
| Auto-heal success rate | N/A | TBD | >80% |
| Memory cache hits | N/A | TBD | >50% |
| Silent failures (continue) | 989 | **817** | <200 |

### Breakdown by Category

**Converted to auto_heal (172 total):**
- Jira API calls: ~25
- GitLab API calls: ~40
- K8s/kubectl calls: ~35
- Bonfire/ephemeral calls: ~15
- Konflux/Tekton calls: ~20
- Git remote calls: ~15
- Monitoring (Prometheus/Alertmanager): ~10
- Slack/other: ~12

**Kept as continue (817 total):**
- Local git operations (git_status, git_branch_create, etc.)
- Compute steps (Python code blocks)
- Memory operations (memory_read, memory_write, etc.)
- Knowledge queries (knowledge_query, code_search)
- Learning operations (learn_tool_fix, check_known_issues)
- Optional enrichment steps

---

## Notes

- The `on_error: auto_heal` option was added to `skill_engine.py`
- Auto-heal detects auth/network errors and tries kube_login/vpn_connect
- Memory logging happens automatically on auto_heal attempts
- Layer 5 learning still runs on all errors for pattern detection
