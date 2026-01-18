# Skill Improvements Audit

## Overview

This document identifies specific opportunities to add:
1. **auto_heal** - Auto-retry with kube_login/vpn_connect
2. **retry** - Simple retry logic for transient failures
3. **memory_load** - Load cached data/patterns before operations
4. **memory_save** - Save results for future use
5. **semantic_search** - Use vector search to find related code/patterns

---

## Improvement Categories

### 1. Memory Load (Before Operations)
Load relevant data from memory before starting:
- Known error patterns for the tools being used
- Cached API responses (Jira issues, MR details)
- Previous successful configurations
- User preferences and history

### 2. Memory Save (After Operations)
Save useful data to memory after completion:
- Successful operation patterns
- Error patterns and their fixes
- API responses for caching
- User activity for personalization

### 3. Semantic Search
Use vector search to find:
- Similar code patterns in the codebase
- Related error handlers
- Architecture documentation
- Past solutions to similar problems

### 4. Auto-Heal
Already implemented for infrastructure tools. Ensure coverage for:
- All kubectl_* calls
- All bonfire_* calls
- All gitlab_* API calls
- All jira_* API calls

### 5. Retry Logic
Add retry for transient failures:
- Network timeouts
- Rate limiting
- Temporary service unavailability

---

## Skill-by-Skill Analysis

### add_project.yaml
**Current State:** Basic error handling, some learning
**Improvements Needed:**
- [ ] **memory_load**: Check if project was previously configured
- [ ] **memory_save**: Save successful project configurations
- [ ] **semantic_search**: Search for similar project setups in knowledge
- [ ] **auto_heal**: Add to `gitlab_mr_list` and `jira_list_issues` calls

### appinterface_check.yaml ✅
**Current State:** Good - has knowledge integration, auto_heal on API calls
**Improvements Needed:**
- [ ] **memory_save**: Cache SaaS file refs for faster subsequent checks
- [ ] **memory_load**: Load previous check results for comparison

### beer.yaml / coffee.yaml
**Current State:** Fun skills, basic error handling
**Improvements Needed:**
- [ ] **memory_load**: Load user preferences (favorite drink, etc.)
- [ ] **memory_save**: Track drink history for personalization

### bootstrap_knowledge.yaml ✅
**Current State:** Good - has vector indexing, knowledge integration
**Improvements Needed:**
- [ ] **memory_save**: Save indexing stats for progress tracking

### cancel_pipeline.yaml
**Current State:** Has auto_heal on Tekton calls
**Improvements Needed:**
- [ ] **memory_load**: Load recent pipeline history
- [ ] **memory_save**: Log cancelled pipelines for audit

### check_ci_health.yaml
**Current State:** Has auto_heal on GitLab calls
**Improvements Needed:**
- [ ] **memory_load**: Load known CI issues
- [ ] **memory_save**: Track CI health trends over time
- [ ] **semantic_search**: Search for related CI configuration

### check_integration_tests.yaml
**Current State:** Has auto_heal on Konflux calls
**Improvements Needed:**
- [ ] **memory_load**: Load previous test results
- [ ] **memory_save**: Track test trends

### check_mr_feedback.yaml
**Current State:** Has auto_heal on GitLab calls
**Improvements Needed:**
- [ ] **memory_load**: Load reviewer preferences
- [ ] **memory_save**: Cache MR feedback for quick access

### check_my_prs.yaml
**Current State:** Has auto_heal on GitLab calls
**Improvements Needed:**
- [ ] **memory_save**: Cache PR list for dashboard

### check_secrets.yaml
**Current State:** Basic error handling
**Improvements Needed:**
- [ ] **auto_heal**: Add to kubectl_get_secrets calls
- [ ] **memory_load**: Load known secret patterns

### ci_retry.yaml
**Current State:** Has auto_heal on GitLab/Tekton calls
**Improvements Needed:**
- [ ] **memory_load**: Load retry history to avoid infinite loops
- [ ] **memory_save**: Track retry success rates

### cleanup_branches.yaml
**Current State:** Has auto_heal on git_fetch
**Improvements Needed:**
- [ ] **memory_load**: Load branch cleanup preferences
- [ ] **memory_save**: Log cleaned branches

### clone_jira_issue.yaml
**Current State:** Has auto_heal on Jira calls
**Improvements Needed:**
- [ ] **memory_load**: Load issue templates
- [ ] **memory_save**: Track cloned issues

### close_issue.yaml
**Current State:** Has auto_heal on Jira calls
**Improvements Needed:**
- [ ] **memory_load**: Load closing templates
- [ ] **memory_save**: Update active issues list

### close_mr.yaml
**Current State:** Has auto_heal on GitLab/Jira calls
**Improvements Needed:**
- [ ] **memory_save**: Update MR tracking

### create_jira_issue.yaml
**Current State:** Has auto_heal on Jira calls
**Improvements Needed:**
- [ ] **memory_load**: Load issue templates and defaults
- [ ] **memory_save**: Track created issues
- [ ] **semantic_search**: Search for similar existing issues

### create_mr.yaml
**Current State:** Has auto_heal on git/GitLab calls
**Improvements Needed:**
- [ ] **memory_load**: Load MR templates
- [ ] **memory_save**: Track created MRs
- [ ] **semantic_search**: Search for related MRs

### debug_prod.yaml ✅
**Current State:** Good - has knowledge integration, pattern loading
**Improvements Needed:**
- [ ] **memory_save**: Save debug session findings
- [ ] **semantic_search**: Search codebase for error handlers (partially done)

### deploy_to_ephemeral.yaml
**Current State:** Has auto_heal on bonfire calls
**Improvements Needed:**
- [ ] **memory_load**: Load previous deployment configs
- [ ] **memory_save**: Track deployment history
- [ ] **retry**: Add retry for namespace reservation

### environment_overview.yaml
**Current State:** Has auto_heal on k8s calls
**Improvements Needed:**
- [ ] **memory_save**: Cache environment state for dashboards

### explain_code.yaml
**Current State:** Basic error handling
**Improvements Needed:**
- [ ] **semantic_search**: Search for related code patterns
- [ ] **memory_load**: Load architecture context
- [ ] **memory_save**: Cache explanations

### extend_ephemeral.yaml
**Current State:** Has auto_heal on bonfire calls
**Improvements Needed:**
- [ ] **memory_load**: Load namespace ownership
- [ ] **memory_save**: Track extensions

### find_similar_code.yaml
**Current State:** Uses semantic search
**Improvements Needed:**
- [ ] **memory_save**: Cache search results

### hotfix.yaml
**Current State:** Has auto_heal on git calls
**Improvements Needed:**
- [ ] **memory_load**: Load hotfix procedures
- [ ] **memory_save**: Track hotfixes
- [ ] **semantic_search**: Find related hotfixes

### investigate_alert.yaml ✅
**Current State:** Good - has knowledge integration, auto_heal
**Improvements Needed:**
- [ ] **memory_save**: Save alert investigation results
- [ ] **semantic_search**: Search for alert-related code (partially done)

### investigate_slack_alert.yaml
**Current State:** Has auto_heal on some calls
**Improvements Needed:**
- [ ] **memory_load**: Load alert patterns
- [ ] **memory_save**: Track Slack alerts

### jira_hygiene.yaml
**Current State:** Has auto_heal on Jira calls
**Improvements Needed:**
- [ ] **memory_load**: Load hygiene rules
- [ ] **memory_save**: Track hygiene actions

### knowledge_refresh.yaml
**Current State:** Basic knowledge operations
**Improvements Needed:**
- [ ] **memory_save**: Track refresh history

### konflux_status.yaml
**Current State:** Basic error handling
**Improvements Needed:**
- [ ] **auto_heal**: Add to Konflux API calls
- [ ] **memory_save**: Cache status for dashboards

### learn_architecture.yaml
**Current State:** Uses semantic search
**Improvements Needed:**
- [ ] **memory_save**: Save learned architecture

### mark_mr_ready.yaml
**Current State:** Has auto_heal on GitLab calls
**Improvements Needed:**
- [ ] **memory_save**: Update MR tracking

### notify_mr.yaml / notify_team.yaml
**Current State:** Has auto_heal on Slack calls
**Improvements Needed:**
- [ ] **memory_load**: Load notification preferences
- [ ] **memory_save**: Track notifications sent

### rebase_pr.yaml
**Current State:** Has auto_heal on git calls
**Improvements Needed:**
- [ ] **memory_load**: Load rebase preferences
- [ ] **retry**: Add retry for merge conflicts

### release_aa_backend_prod.yaml / release_to_prod.yaml
**Current State:** Has auto_heal on some calls
**Improvements Needed:**
- [ ] **memory_load**: Load release checklist
- [ ] **memory_save**: Track releases
- [ ] **semantic_search**: Find release-related changes

### review_all_prs.yaml
**Current State:** Has auto_heal on GitLab calls
**Improvements Needed:**
- [ ] **memory_save**: Cache review queue

### review_pr.yaml ✅
**Current State:** Good - has knowledge integration, auto_heal
**Improvements Needed:**
- [ ] **memory_save**: Save review feedback for author coaching
- [ ] **semantic_search**: Enhanced pattern matching (partially done)

### rollout_restart.yaml
**Current State:** Has auto_heal on kubectl calls
**Improvements Needed:**
- [ ] **memory_load**: Load rollout preferences
- [ ] **memory_save**: Track rollouts
- [ ] **retry**: Add retry for rollout failures

### scale_deployment.yaml
**Current State:** Has auto_heal on kubectl calls
**Improvements Needed:**
- [ ] **memory_load**: Load scaling limits
- [ ] **memory_save**: Track scaling events

### scan_vulnerabilities.yaml
**Current State:** Has auto_heal on Quay calls
**Improvements Needed:**
- [ ] **memory_save**: Track vulnerability history

### schedule_meeting.yaml
**Current State:** Basic error handling
**Improvements Needed:**
- [ ] **auto_heal**: Add to calendar API calls
- [ ] **memory_load**: Load scheduling preferences

### silence_alert.yaml
**Current State:** Has auto_heal on alertmanager calls
**Improvements Needed:**
- [ ] **memory_load**: Load silence templates
- [ ] **memory_save**: Track silences

### sprint_planning.yaml
**Current State:** Has auto_heal on Jira calls
**Improvements Needed:**
- [ ] **memory_load**: Load sprint templates
- [ ] **memory_save**: Track sprint plans

### standup_summary.yaml
**Current State:** Has auto_heal on some calls
**Improvements Needed:**
- [ ] **memory_load**: Load standup preferences
- [ ] **memory_save**: Save standup summaries

### start_work.yaml ✅
**Current State:** Good - has auto_heal, knowledge integration
**Improvements Needed:**
- [ ] **memory_save**: Enhanced work tracking
- [ ] **semantic_search**: Find related work items

### submit_expense.yaml
**Current State:** Basic error handling
**Improvements Needed:**
- [ ] **memory_load**: Load expense templates
- [ ] **memory_save**: Track expenses

### sync_branch.yaml
**Current State:** Has auto_heal on git calls
**Improvements Needed:**
- [ ] **retry**: Add retry for merge conflicts

### test_mr_ephemeral.yaml ✅
**Current State:** Good - has auto_heal on most calls
**Improvements Needed:**
- [ ] **memory_load**: Load previous test results
- [ ] **memory_save**: Track test history
- [ ] **semantic_search**: Find related test patterns

### update_docs.yaml
**Current State:** Basic error handling
**Improvements Needed:**
- [ ] **semantic_search**: Find related documentation
- [ ] **memory_save**: Track doc updates

### weekly_summary.yaml
**Current State:** Has auto_heal on some calls
**Improvements Needed:**
- [ ] **memory_load**: Load summary templates
- [ ] **memory_save**: Archive summaries

---

## Priority Implementation Order

### Phase 1: High-Impact Memory Operations
1. **start_work.yaml** - Save active work to memory
2. **test_mr_ephemeral.yaml** - Cache test results
3. **debug_prod.yaml** - Save debug findings
4. **review_pr.yaml** - Save review feedback

### Phase 2: Semantic Search Integration
1. **create_jira_issue.yaml** - Search for similar issues
2. **create_mr.yaml** - Search for related MRs
3. **explain_code.yaml** - Search for patterns
4. **hotfix.yaml** - Find related hotfixes

### Phase 3: Caching for Performance
1. **check_my_prs.yaml** - Cache PR list
2. **environment_overview.yaml** - Cache env state
3. **appinterface_check.yaml** - Cache SaaS refs
4. **weekly_summary.yaml** - Cache summaries

### Phase 4: Retry Logic
1. **deploy_to_ephemeral.yaml** - Retry namespace reservation
2. **rollout_restart.yaml** - Retry rollouts
3. **sync_branch.yaml** - Retry on conflicts
4. **rebase_pr.yaml** - Retry on conflicts

---

## Implementation Patterns

### Memory Load Pattern
```yaml
- name: load_cached_data
  description: "Load cached data from memory"
  tool: memory_read
  args:
    key: "cache/{{ skill_name }}/{{ unique_id }}"
  output: cached_data
  on_error: continue

- name: check_cache_valid
  compute: |
    from datetime import datetime, timedelta

    cache_valid = False
    if cached_data and cached_data.get('timestamp'):
      cache_time = datetime.fromisoformat(cached_data['timestamp'])
      cache_valid = datetime.now() - cache_time < timedelta(hours=1)

    result = {"valid": cache_valid, "data": cached_data if cache_valid else None}
  output: cache_check
```

### Memory Save Pattern
```yaml
- name: save_results_to_memory
  description: "Save results for future use"
  tool: memory_write
  args:
    key: "cache/{{ skill_name }}/{{ unique_id }}"
    content: |
      timestamp: "{{ datetime.now().isoformat() }}"
      data: {{ results | tojson }}
  on_error: continue
```

### Semantic Search Pattern
```yaml
- name: search_related_code
  description: "Find related code patterns"
  tool: code_search
  args:
    query: "{{ error_message or search_term }}"
    project: "{{ project_name }}"
    limit: 5
  output: related_code
  on_error: continue

- name: parse_search_results
  compute: |
    results = []
    if related_code:
      for match in related_code.get('matches', []):
        results.append({
          "file": match.get('file'),
          "snippet": match.get('content', '')[:200],
          "relevance": match.get('score', 0),
        })
    result = {"found": len(results) > 0, "matches": results[:5]}
  output: search_results
```

### Retry Pattern
```yaml
- name: operation_with_retry
  description: "Operation with retry logic"
  tool: some_tool
  args:
    param: "{{ value }}"
  output: result
  on_error: continue
  retry:
    max_attempts: 3
    delay_seconds: 5
    retry_on:
      - "timeout"
      - "connection refused"
      - "rate limit"
```

---

## Metrics to Track

| Metric | Before | Current | Target |
|--------|--------|---------|--------|
| auto_heal calls | 0 | **172** ✅ | 200+ |
| memory operations | ~50 | **217** ✅ | 250+ |
| code_search calls | ~20 | **54** ✅ | 60+ |
| knowledge_query calls | ~30 | **59** ✅ | 70+ |
| on_error: continue | 989 | **817** | <500 |
| Skills with retry logic | 0 | 0 | 15+ |
| Cache hit rate | N/A | N/A | >50% |
| Auto-heal success rate | N/A | N/A | >80% |

### Summary of Changes Made

1. **Added `on_error: auto_heal`** to 172 infrastructure/API tool calls
2. **Memory operations** increased from ~50 to 217 across skills
3. **Semantic search** (code_search) used in 18 skills with 54 total calls
4. **Knowledge integration** (knowledge_query) used in 59 calls
5. **Created skill engine support** for `on_error: auto_heal` with:
   - Auth error detection (401, 403, unauthorized)
   - Network error detection (timeout, connection refused)
   - Auto-fix with kube_login() or vpn_connect()
   - Retry after fix
   - Memory logging of all auto-heal attempts
