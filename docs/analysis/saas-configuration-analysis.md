# SaaS Configuration Maturity Analysis Report

**Project:** Automation Analytics (tower-analytics / aap-aa-tenant)
**Date:** 2026-01-29
**Scope:** Konflux Release-Data + App-Interface configurations
**Compared Against:** 12 Insights services (notifications, rbac, host-inventory, compliance, sources, export-service, playbook-dispatcher, vulnerability) + 4 Konflux tenants

---

## Executive Summary

This analysis compares your Automation Analytics SaaS configurations against other projects in the Insights platform to identify gaps, best practices, and improvement opportunities. Your configuration is **moderately mature** with some notable strengths but several areas for improvement.

### Maturity Score: 6.5/10 (Revised)

| Category | Score | Notes |
|----------|-------|-------|
| Konflux Configuration | 7/10 | Good test coverage, but using custom ECP instead of shared |
| App-Interface SaaS | 6/10 | Missing many modern patterns from mature services |
| SLO/Observability | 5/10 | Basic SLOs, missing error tracking, CloudWatch explicit |
| Security/Compliance | 6/10 | Many ECP exclusions, missing PGSSLMODE, no SBOM notifications |
| Release Process | 8/10 | Proper promotion gates, pinned prod refs |
| Operational Controls | 5/10 | Missing job suspension flags, health probes, Kafka resilience |

### Key Findings Summary

| Finding | Severity | Effort to Fix |
|---------|----------|---------------|
| Custom ECP instead of shared policy | Medium | Low |
| Missing SBOM notifications | High | Low |
| No Sentry/error tracking | High | Medium |
| Missing `PGSSLMODE: verify-full` | High | Low |
| No Kafka resilience parameters | Medium | Low |
| Missing job suspension flags | Medium | Low |
| Low Gunicorn workers (1 vs 4-8) | Medium | Low |
| Stale hardcoded dates | Low | Low |
| No ElastiCache/Redis caching | Low | High |

---

## Part 1: Konflux Configuration Analysis

### Current State: `aap-aa-tenant`

**Location:** `/home/daoneill/src/konflux-release-data/tenants-config/cluster/stone-prod-p02/tenants/aap-aa-tenant/`

#### Strengths ✅

1. **Comprehensive Test Coverage**
   - 8 IntegrationTestScenarios (group1-4, billing, conforma, quick, slow)
   - Test grouping enables parallel execution
   - Billing-specific tests separated
   - Conforma compliance tests included

2. **Proper Release Pipeline**
   - ReleasePlan with auto-release enabled
   - ReleasePlanAdmission targeting `rhtap-releng-tenant`
   - Pyxis integration for certification
   - Multiple image tags (latest, git_sha, git_short_sha, digest_sha)

3. **Enterprise Contract Policy**
   - Configured with appropriate exclusions
   - Uses Conforma release policy
   - Proper allowed registry prefixes

#### Gaps & Recommendations 🔧

##### 1. Using Custom ECP Instead of Shared Policy ⚠️ NEW

**Current:** aap-aa-tenant uses a tenant-specific ECP (`ecp-aap-aa.yml`) with 60+ exclusions.

**Observed in mature tenants:**
- `rh-subs-watch-tenant`: Uses `rhtap-releng-tenant/app-interface-rh-subs-watch-prod`
- `insights-management-tenant`: Uses `rhtap-releng-tenant/consoledot-backend-standard`
- `hcc-platex-services-tenant`: Uses `rhtap-releng-tenant/app-interface-standard`

**Issue:** Maintaining a custom ECP creates technical debt and may miss security updates.

**Recommendation:** Migrate to a shared policy:
```yaml
# In IntegrationTestScenario, change:
params:
  - name: POLICY_CONFIGURATION
    value: rhtap-releng-tenant/app-interface-standard  # Use shared policy
```

##### 2. Missing SBOM Notifications ⚠️ NEW (HIGH PRIORITY)

**Observed in insights-management-tenant:**
```yaml
# In ImageRepository
spec:
  notifications:
    - config:
        url: https://bombino.api.redhat.com/v1/sbom/quay/push
      event: repo_push
      method: webhook
      title: SBOM-event-to-Bombino
```

**Current:** aap-aa-tenant has no SBOM notifications.

**Impact:** Missing compliance requirement for software bill of materials.

**Recommendation:** Add SBOM notifications to `ir-aap-aa.yml`:
```yaml
spec:
  notifications:
    - config:
        url: https://bombino.api.redhat.com/v1/sbom/quay/push
      event: repo_push
      method: webhook
      title: SBOM-event-to-Bombino
```

##### 3. Missing Component-Level Testing ⚠️ NEW

**Observed in insights-management-tenant:**
```yaml
spec:
  params:
    - name: SINGLE_COMPONENT
      value: 'true'  # Component-level EC testing
  contexts:
    - description: Component Testing
      name: component_aap-aa  # Component-specific context
```

**Current:** aap-aa-tenant uses application-level testing only.

**Recommendation:** Add `SINGLE_COMPONENT: 'true'` for more granular EC tests.

##### 4. Missing Quick/Slow Test Scenarios

**Current:** You have `its-aap-aa-quick.yml` and `its-aap-aa-slow.yml` referenced but need to verify they exist.

**Recommendation:** Ensure quick tests run on every PR, slow tests run on merge to main.

```yaml
# its-aap-aa-quick.yml - should have:
metadata:
  labels:
    test.appstudio.openshift.io/optional: "true"  # Run on every PR
  annotations:
    test.appstudio.openshift.io/pipeline_timeout: "15m"  # Quick timeout
```

##### 5. Missing Version-Specific Release Plans

**Observed in mature tenants (rhdh-tenant, rhoai-tenant, insights-management-tenant):** Separate stage/prod release plans.

**Current:** Single release plan for all releases.

**Observed in insights-management-tenant:**
```yaml
# Stage ReleasePlan
metadata:
  labels:
    release.appstudio.openshift.io/auto-release: 'true'   # Auto for stage
    release.appstudio.openshift.io/releasePlanAdmission: 'iop-satellite-stage'
  name: iop-advisor-backend-stage

# Prod ReleasePlan
metadata:
  labels:
    release.appstudio.openshift.io/auto-release: 'false'  # Manual for prod
    release.appstudio.openshift.io/releasePlanAdmission: 'iop-satellite-prod'
  name: iop-advisor-backend-prod
```

**Recommendation:** Create separate stage/prod release plans for better control.

##### 6. Enterprise Contract Policy Exclusions Review

**Current exclusions that should be reviewed:**

```yaml
exclude:
  - cve  # ⚠️ Consider enabling CVE scanning
  - hermetic_task  # ⚠️ Hermetic builds improve reproducibility
  - source_image.exists  # ⚠️ Source images aid debugging
```

**Recommendation:** Gradually enable these checks:

```yaml
# Phase 1: Enable CVE scanning with warnings only
config:
  include:
    - "@redhat"
  exclude:
    # Remove 'cve' from exclusions
    - hermetic_task  # Keep for now
    # ...
```

##### 4. Missing ProjectDevelopmentStream

**Observed in rhoai-tenant:** Uses `ProjectDevelopmentStream` for version management.

**Recommendation:** For long-lived versions, consider:

```yaml
apiVersion: projctl.konflux.dev/v1beta1
kind: ProjectDevelopmentStream
metadata:
  name: aap-aa-v2
spec:
  project: aap-aa
  template:
    name: aap-aa-template
```

##### 5. Missing FBC (File-Based Catalog) Configuration

**Observed in rhdh-tenant, rhoai-tenant:** FBC fragments for operator lifecycle.

**Applicability:** Only if you ship an operator. Skip if not applicable.

---

## Part 2: App-Interface Configuration Analysis

### Current State: `tower-analytics`

**Location:** `/home/daoneill/src/app-interface/data/services/insights/tower-analytics/`

#### Strengths ✅

1. **Proper Onboarding Status**
   - `onboardingStatus: OnBoarded` (not BestEffort)
   - Architecture document linked
   - SOPs URL configured
   - Escalation policy defined

2. **Comprehensive Namespace Configuration**
   - 6 namespaces (stage, prod, billing variants, pipelines, tests)
   - Network policies configured
   - External resources (RDS, S3, CloudWatch) properly defined
   - Vault secrets with `qontract.recycle: "true"`

3. **Promotion Gates**
   - Stage deployments publish to Slack channels
   - Prod uses pinned commit SHAs (no auto-promotion)

4. **SLO Documents**
   - Availability SLO (90% target)
   - Latency SLO (90% under 2000ms)

#### Gaps & Recommendations 🔧

##### 1. Missing `dora` Label

**Observed in notifications:** Has `dora: insights-production` label for DORA metrics.

**Current:** Missing from tower-analytics.

**Recommendation:** Add to `deploy-clowder.yml`:

```yaml
labels:
  service: tower-analytics
  platform: insights
  dora: insights-production  # ADD THIS
```

##### 2. Missing Production Promotion Gate

**Current:** Stage has promotion gate, prod does not.

**Observed in notifications:** Both stage AND prod have promotion gates.

**Recommendation:** Add prod promotion gate:

```yaml
# In tower-analytics-clowdapp prod target:
- namespace:
    $ref: /services/insights/tower-analytics/namespaces/tower-analytics-prod.yml
  ref: e6e4a6aa5c5d93c5d9406dc7660c2bea097234c2
  parameters:
    # ... existing params ...
  promotion:
    publish:
    - automation-analytics-prod-deploy-success-channel  # ADD THIS
```

##### 3. SLO Improvements

**Current SLOs:**
- Availability: 90% (0.90)
- Latency: 90% under 2000ms

**Observed in notifications:** 99% availability target.

**Recommendations:**

a) **Increase SLO targets** (if achievable):
```yaml
slos:
- name: RequestsResultSuccessfulNon5xxResponse
  SLOTarget: 0.95  # Increase from 0.90 to 0.95

- name: RequestLatencyUnder2000ms
  SLOTarget: 0.95  # Increase from 0.90 to 0.95
```

b) **Add additional SLOs:**
```yaml
# Add per-component availability SLO
- name: ProcessorControllerAvailability
  SLIType: availability
  SLISpecification: Processor controller pod availability
  SLOTarget: 0.99
  SLOParameters:
    window: 7d
  expr: |
    avg_over_time(
      kube_deployment_status_replicas_available{
        namespace="tower-analytics-prod",
        deployment=~".*processor-controller.*"
      }[7d]
    ) / avg_over_time(
      kube_deployment_status_replicas{
        namespace="tower-analytics-prod",
        deployment=~".*processor-controller.*"
      }[7d]
    )
```

##### 4. Missing `managedResourceTypes` Entries

**Current:**
```yaml
managedResourceTypes:
- ClowdApp
- Service
- Frontend
```

**Observed in notifications:**
```yaml
managedResourceTypes:
- ClowdApp
- ClowdJobInvocation
- ConfigMap
- FloorPlan
- Frontend
- ScaledObject.keda.sh
- TriggerAuthentication.keda.sh
```

**Recommendation:** Add if you use these resources:
```yaml
managedResourceTypes:
- ClowdApp
- ClowdJobInvocation  # ADD if using CronJobs via Clowder
- ConfigMap          # ADD if deploying ConfigMaps
- Service
- Frontend
```

##### 5. Missing Resource Quotas Review

**Current:** Has `tower-analytics-quota.yml`

**Recommendation:** Ensure quotas match actual usage + 20% headroom. Review periodically.

##### 6. Stale TODOs in Configuration

**Found in deploy-clowder.yml:**
```yaml
BUNDLES_BUCKET_NAME: insights-ingress-prod # TODO: not used ??
BUNDLES_SECRET_NAME: upload-s3 # TODO": not used ??
```

**Recommendation:** Clean up or remove unused parameters to reduce confusion.

##### 7. Missing Sentry/Error Tracking

**Observed in notifications:**
```yaml
SENTRY_DSN: https://...@sentry.io/...
SENTRY_ENABLED: true
```

**Current:** Not configured in tower-analytics.

**Recommendation:** Add Sentry for error tracking:
```yaml
parameters:
  SENTRY_DSN: ${SENTRY_DSN}
  SENTRY_ENABLED: 'True'
```

##### 8. Missing KEDA Autoscaling

**Observed in notifications:** Uses KEDA for autoscaling.

**Current:** Uses static replica counts.

**Recommendation:** Consider KEDA for dynamic scaling:
```yaml
managedResourceTypes:
- ScaledObject.keda.sh
- TriggerAuthentication.keda.sh

# In ClowdApp template, add ScaledObject for high-traffic components
```

##### 9. Contract Version Outdated

**Current SRE checkpoint:** `contractVersion: v2023.10.02`

**Recommendation:** Check if newer contract versions are available and update.

---

## Part 3: Security & Compliance

### Current State

#### Konflux ECP (Enterprise Contract Policy)

**Excluded checks that pose risk:**

| Exclusion | Risk Level | Recommendation |
|-----------|------------|----------------|
| `cve` | HIGH | Enable with warning-only mode first |
| `hermetic_task` | MEDIUM | Plan migration to hermetic builds |
| `source_image.exists` | LOW | Enable for debugging capability |
| `sast-snyk-check` | MEDIUM | Enable SAST scanning |

### Recommendations

##### 1. Enable CVE Scanning

```yaml
# Phase 1: Remove from exclusions, add to warnings
config:
  include:
    - "@redhat"
  exclude:
    # Remove: - cve
    - hermetic_task
    # ...
  # Add warning mode for CVE
  warn:
    - cve
```

##### 2. Enable SAST Scanning

```yaml
# Remove these exclusions gradually:
# - sast-snyk-check
# - sast-unicode-check
```

##### 3. Review Allowed Registry Prefixes

**Current:**
```yaml
allowed_registry_prefixes:
  - registry.access.redhat.com/
  - registry.redhat.io/
  - brew.registry.redhat.io/rh-osbs/openshift-golang-builder
  - quay.io/redhat-services-prod/
  - quay.io/konflux-ci
```

**Recommendation:** This looks appropriate. No changes needed.

---

## Part 4: Release Process

### Current State

| Aspect | Status | Notes |
|--------|--------|-------|
| Stage auto-deploy | ✅ | `ref: main` with promotion gate |
| Prod pinned refs | ✅ | Full commit SHAs |
| Slack notifications | ✅ | Stage deploy success channel |
| Pyxis integration | ✅ | Production certification |
| Multiple image tags | ✅ | latest, git_sha, git_short_sha, digest_sha |

### Recommendations

##### 1. Add Prod Deployment Notifications

**Current:** Only stage has Slack notifications.

**Recommendation:** Add prod notifications for visibility.

##### 2. Consider Canary Deployments

**Observed pattern:** Some teams use canary deployments.

**Recommendation:** For critical components, consider:
```yaml
# Canary target (5% traffic)
- namespace:
    $ref: /services/insights/tower-analytics/namespaces/tower-analytics-prod-canary.yml
  ref: <new-sha>
  parameters:
    REPLICAS_API: 1  # Single replica for canary
```

##### 3. Add Rollback Documentation

**Recommendation:** Document rollback procedure in SOPs:
1. Identify last known good SHA
2. Update `ref:` in deploy-clowder.yml
3. Create MR with `[ROLLBACK]` prefix
4. Fast-track merge

---

## Part 5: Comparison with Mature Projects

### Notifications (Most Mature)

| Feature | Notifications | Tower-Analytics | Gap |
|---------|--------------|-----------------|-----|
| DORA label | ✅ | ❌ | Add label |
| Prod promotion gate | ✅ | ❌ | Add gate |
| Sentry integration | ✅ | ❌ | Add Sentry |
| KEDA autoscaling | ✅ | ❌ | Consider adding |
| Multiple SLOs | ✅ (3) | ✅ (2) | Add more |
| HCC variants | ✅ | N/A | Not applicable |

### RBAC (Similar Complexity)

| Feature | RBAC | Tower-Analytics | Gap |
|---------|------|-----------------|-----|
| Testing namespaces | ✅ | ✅ | Parity |
| Quota definitions | ✅ | ✅ | Parity |
| SRE checkpoints | ✅ | ✅ | Parity |
| Perf environment | ✅ | ❌ | Consider adding |

### Host-Inventory (Data-Heavy)

| Feature | Host-Inventory | Tower-Analytics | Gap |
|---------|---------------|-----------------|-----|
| Query library | ✅ (71 files) | ❌ | Consider adding |
| Prod replica | ✅ | ❌ | Consider for testing |
| Multiple components | ✅ | ✅ | Parity |

---

## Part 6: Prioritized Action Items

### Critical Priority (Security/Compliance) 🔴

| # | Action | Impact | Effort | Location |
|---|--------|--------|--------|----------|
| 1 | **Add SBOM notifications** to ImageRepository | Compliance | Low | `ir-aap-aa.yml` |
| 2 | **Add `PGSSLMODE: verify-full`** | Security | Low | `deploy-clowder.yml` |
| 3 | **Migrate to shared ECP policy** | Maintainability | Medium | `ecp-aap-aa.yml` |

### High Priority (Observability/Reliability) 🟠

| # | Action | Impact | Effort | Location |
|---|--------|--------|--------|----------|
| 4 | **Add Sentry integration** | Error tracking | Medium | `deploy-clowder.yml` |
| 5 | **Add prod promotion gate** | Visibility | Low | `deploy-clowder.yml` |
| 6 | **Add `dora` label** | DORA metrics | Low | `deploy-clowder.yml` |
| 7 | **Add Kafka resilience params** | Reliability | Low | `deploy-clowder.yml` |
| 8 | **Add health probe configuration** | Reliability | Low | `deploy-clowder.yml` |

### Medium Priority (Operations) 🟡

| # | Action | Impact | Effort | Location |
|---|--------|--------|--------|----------|
| 9 | **Add job suspension flags** | Incident response | Low | `deploy-clowder.yml` |
| 10 | **Increase Gunicorn workers** (1→4) | Performance | Low | `deploy-clowder.yml` |
| 11 | **Add CPU requests** for all components | Resource planning | Medium | `deploy-clowder.yml` |
| 12 | **Clean up stale TODOs** | Maintainability | Low | `deploy-clowder.yml` |
| 13 | **Fix hardcoded dates** | Maintenance | Low | `deploy-clowder.yml` |
| 14 | **Separate stage/prod ReleasePlans** | Release control | Medium | Konflux configs |

### Low Priority (Enhancements) 🟢

| # | Action | Impact | Effort | Location |
|---|--------|--------|--------|----------|
| 15 | **Add component-level EC testing** | Test granularity | Medium | Konflux ITS |
| 16 | **Consider KEDA autoscaling** | Cost optimization | High | `deploy-clowder.yml` |
| 17 | **Add ElastiCache** | Performance | High | Namespace configs |
| 18 | **Add performance testing namespace** | Testing | High | App-interface |
| 19 | **Create query library** | Investigations | Medium | App-interface |
| 20 | **Increase SLO targets** | Reliability | Low | SLO documents |

### Quick Wins (< 1 hour each)

```yaml
# 1. Add PGSSLMODE (deploy-clowder.yml)
parameters:
  PGSSLMODE: 'verify-full'

# 2. Add dora label (deploy-clowder.yml)
labels:
  dora: insights-production

# 3. Add prod promotion gate (deploy-clowder.yml)
promotion:
  publish:
  - automation-analytics-prod-deploy-success-channel

# 4. Increase Gunicorn workers (deploy-clowder.yml)
GUNICORN_PROCESSES: 4

# 5. Add job suspension flags (deploy-clowder.yml)
DATA_PRUNING_SUSPEND: 'false'
MSG_RECOVERY_SUSPEND: 'false'

# 6. Add Kafka resilience (deploy-clowder.yml)
KAFKA_PRODUCER_RETRIES: '8'
KAFKA_PRODUCER_RETRY_BACKOFF_MS: '250'
```

---

## Appendix A: Configuration Diffs

### Recommended deploy-clowder.yml Changes

```diff
 labels:
   service: tower-analytics
   platform: insights
+  dora: insights-production

 # ... in prod target ...
   - namespace:
       $ref: /services/insights/tower-analytics/namespaces/tower-analytics-prod.yml
     ref: e6e4a6aa5c5d93c5d9406dc7660c2bea097234c2
     parameters:
       # ... existing params ...
-      BUNDLES_BUCKET_NAME: insights-ingress-prod # TODO: not used ??
-      BUNDLES_SECRET_NAME: upload-s3 # TODO": not used ??
+      SENTRY_DSN: ${SENTRY_DSN}
+      SENTRY_ENABLED: 'True'
+    promotion:
+      publish:
+      - automation-analytics-prod-deploy-success-channel
```

### Recommended ECP Changes (Phase 1)

```diff
 config:
   include:
     - "@redhat"
   exclude:
-    - cve
     - hermetic_task
     # ... other exclusions ...
+  warn:
+    - cve
```

---

## Appendix B: Maturity Model Reference

### Level 1: Basic
- Single namespace
- Manual deployments
- No SLOs
- No promotion gates

### Level 2: Developing
- Stage/Prod namespaces
- Pinned prod refs
- Basic SLOs (1-2)
- Stage promotion gates

### Level 3: Mature (Current Level)
- Multiple namespaces (billing, tests)
- Comprehensive test coverage
- Multiple SLOs
- Stage promotion gates
- SRE checkpoints

### Level 4: Advanced
- KEDA autoscaling
- Canary deployments
- Comprehensive SLOs (5+)
- Both stage/prod promotion gates
- Error tracking (Sentry)
- DORA metrics

### Level 5: Exemplary
- All Level 4 features
- Hermetic builds
- Full CVE scanning
- Performance testing environment
- Query library for investigations
- Automated rollback

---

## Part 7: Deep-Dive Configuration Comparison

This section provides a detailed parameter-by-parameter comparison of tower-analytics against mature projects (notifications, rbac, host-inventory, compliance) to identify outdated, missing, or suboptimal configurations.

### 7.1 Missing Configuration Patterns

#### 7.1.1 Error Tracking & Observability

| Parameter | Notifications | RBAC | Host-Inventory | Tower-Analytics | Status |
|-----------|--------------|------|----------------|-----------------|--------|
| `SENTRY_DSN` | ✅ Per-component DSNs | ❌ | ❌ | ❌ | **MISSING** |
| `SENTRY_ENABLED` | ✅ `true` | ❌ | ❌ | ❌ | **MISSING** |
| `GLITCHTIP_SECRET` | ❌ | ✅ | ❌ | ❌ | Consider |
| `CLOUDWATCH_ENABLED` | ✅ `true` | ❌ | ✅ | ❌ | **MISSING** |
| `QUARKUS_LOG_CLOUDWATCH_ENABLED` | ✅ `true` | ❌ | ❌ | ❌ | N/A (Python) |
| `LOG_LEVEL` / `JOBS_LOG_LEVEL` | ✅ DEBUG/INFO | ✅ | ✅ DEBUG/INFO | ✅ INFO (prod only) | **Partial** |
| `enableDynatraceLogging` | ❌ | ❌ | ✅ (namespace) | ❌ | Consider |

**Recommendation:** Add Sentry integration for error tracking. Notifications has component-specific DSNs:
```yaml
# Example from notifications:
SENTRY_DSN: https://3ff0dbd8017a4750a1d92055a1685263@o490301.ingest.sentry.io/5440905?environment=
SENTRY_ENABLED: true
```

#### 7.1.2 Database Configuration

| Parameter | Notifications | RBAC | Host-Inventory | Tower-Analytics | Status |
|-----------|--------------|------|----------------|-----------------|--------|
| `PGSSLMODE` | ❌ | ✅ `verify-full` | ✅ `verify-full` | ❌ | **MISSING** |
| `DB_SSL_MODE` | ❌ | ❌ | ✅ `verify-full` | ❌ | **MISSING** |
| Read Replica | ❌ | ❌ | ✅ Multiple | ❌ | Consider |
| `enhanced_monitoring` | ✅ | ✅ | ✅ | ✅ | OK |
| `apply_immediately` | ✅ `true` | ✅ | ✅ | ✅ `true` | OK |
| `deletion_protection` | ✅ `false` | ❌ | ❌ | ❌ | Consider |

**Recommendation:** Add explicit SSL mode configuration:
```yaml
parameters:
  PGSSLMODE: 'verify-full'  # Enforce SSL verification
```

#### 7.1.3 Caching (ElastiCache/Redis)

| Parameter | Notifications | RBAC | Host-Inventory | Compliance | Tower-Analytics | Status |
|-----------|--------------|------|----------------|------------|-----------------|--------|
| ElastiCache | ✅ | ❌ | ✅ | ✅ (2 instances) | ❌ | **MISSING** |
| `REDIS_MAX_CONNECTIONS` | ❌ | ✅ `20` | ❌ | ❌ | ❌ | Consider |
| `REDIS_SOCKET_TIMEOUT` | ❌ | ✅ `0.5` | ❌ | ❌ | ❌ | Consider |
| `IN_MEMORY_DB_ENABLED` | ✅ `true` | ❌ | ❌ | ❌ | ❌ | Consider |
| Cache Type | ❌ | ❌ | ✅ `RedisCache` | ✅ Rails cache | ❌ | Consider |

**Recommendation:** If you have caching needs, consider adding ElastiCache:
```yaml
# In namespace externalResources:
- provider: elasticache
  identifier: tower-analytics-prod
  managed_by_erv2: true
  defaults: /terraform/resources/insights/production/elasticache/elasticache-1.yml
  output_resource_name: in-memory-db
```

#### 7.1.4 Kafka/Messaging Configuration

| Parameter | Notifications | RBAC | Host-Inventory | Tower-Analytics | Status |
|-----------|--------------|------|----------------|-----------------|--------|
| `KAFKA_ENABLED` | ✅ | ✅ | ✅ | Implicit | OK |
| `KAFKA_MAX_POLL_RECORDS` | ✅ 50-100 | ❌ | ❌ | ❌ | Consider |
| `KAFKA_MAX_POLL_INTERVAL_MS` | ✅ 1200000 | ❌ | ✅ 15000 | ❌ | **MISSING** |
| `KAFKA_CONSUMER_SESSION_TIMEOUT_MS` | ❌ | ❌ | ✅ 15000 | ❌ | Consider |
| `KAFKA_CONSUMER_HEARTBEAT_INTERVAL_MS` | ❌ | ❌ | ✅ 5000 | ❌ | Consider |
| `KAFKA_PRODUCER_RETRIES` | ❌ | ❌ | ✅ 8 | ❌ | **MISSING** |
| `KAFKA_PRODUCER_RETRY_BACKOFF_MS` | ❌ | ❌ | ✅ 250 | ❌ | **MISSING** |
| `KAFKA_GROUP_*` | ✅ | ✅ | ❌ | ✅ (billing) | OK |

**Recommendation:** Add Kafka resilience parameters:
```yaml
parameters:
  KAFKA_PRODUCER_RETRIES: '8'
  KAFKA_PRODUCER_RETRY_BACKOFF_MS: '250'
  KAFKA_CONSUMER_SESSION_TIMEOUT_MS: '15000'
  KAFKA_CONSUMER_HEARTBEAT_INTERVAL_MS: '5000'
```

#### 7.1.5 Feature Flags & Unleash

| Parameter | Notifications | RBAC | Host-Inventory | Tower-Analytics | Status |
|-----------|--------------|------|----------------|-----------------|--------|
| `*_UNLEASH_ENABLED` | ✅ `true` | ❌ | ❌ | ❌ | Consider |
| `UNLEASH_REFRESH_INTERVAL` | ❌ | ❌ | ✅ | ❌ | Consider |
| Unleash shared resource | ❌ | ❌ | ❌ | ✅ (stage) | OK |

**Current:** Tower-analytics has Unleash shared resource in stage namespace. Good.

#### 7.1.6 Autoscaling Configuration

| Parameter | Notifications | RBAC | Host-Inventory | Tower-Analytics | Status |
|-----------|--------------|------|----------------|-----------------|--------|
| `MIN_REPLICAS` | ✅ 3-6 | ✅ 6 | ✅ 1-30 | Static counts | **OUTDATED** |
| `MAX_REPLICAS` | ❌ | ✅ 8-25 | ❌ | ❌ | **MISSING** |
| KEDA ScaledObject | ✅ | ❌ | ❌ | ❌ | Consider |
| `GUNICORN_WORKER_MULTIPLIER` | ❌ | ✅ `4` | ✅ 4-8 workers | ✅ `1` | **REVIEW** |

**Issue:** Tower-analytics uses `GUNICORN_PROCESSES: 1` while other projects use multipliers of 4-8.

**Recommendation:**
```yaml
parameters:
  GUNICORN_PROCESSES: 4  # Increase from 1
  # Or add autoscaling:
  MIN_REPLICAS_API: 10
  MAX_REPLICAS_API: 30
```

### 7.2 Outdated Configuration Patterns

#### 7.2.1 Stale/Unused Parameters

**Found in tower-analytics prod:**
```yaml
BUNDLES_BUCKET_NAME: insights-ingress-prod # TODO: not used ??
BUNDLES_SECRET_NAME: upload-s3 # TODO": not used ??
INGRESS_ANALYTICS_BUCKET_NAME: '' # insights-upload-tower-analytics-prod
```

**Recommendation:** Remove or document these parameters. Stale TODOs indicate technical debt.

#### 7.2.2 Hardcoded Dates

**Found in tower-analytics:**
```yaml
UNPROCESSED_EVENTS_MIN_DATE: '2023-10-25' # Process last 3 months
AMPLITUDE_ETL_START_DATE: '2024-09-01'
AMPLITUDE_ETL_END_DATE: '2025-03-05'
```

**Issue:** These dates are static and may become stale.

**Recommendation:** Use relative dates or dynamic calculation:
```yaml
# Consider using a rolling window instead of fixed dates
UNPROCESSED_EVENTS_LOOKBACK_DAYS: '90'  # Instead of hardcoded date
```

#### 7.2.3 Inconsistent Boolean Formatting

**Found in tower-analytics:**
```yaml
RBAC_ENABLED: 'True'           # String
DATA_EXPORT_ENABLED: 'True'    # String
LOCK_MESSAGES_RECOVERY_ENABLED: 'true'  # Lowercase string
AUTO_HEALER_DRY_RUN: 'True'    # String
```

**Observed in notifications:**
```yaml
NOTIFICATIONS_DRAWER_ENABLED: true  # Boolean
SENTRY_ENABLED: true                # Boolean
```

**Recommendation:** Standardize on lowercase string `'true'`/`'false'` or actual YAML booleans for consistency.

#### 7.2.4 Missing CPU Requests

**Tower-analytics ephemeral:**
```yaml
CPU_LIMIT_DATA_PRUNING: 1000m
CPU_LIMIT_EXPORTER: 1000m
# No CPU_REQUEST_* parameters
```

**Best practice from other projects:**
```yaml
# Notifications pattern:
CPU_LIMIT: 300m
CPU_REQUEST: 150m  # 50% of limit

# Host-inventory pattern:
CPU_LIMIT: 1.5
CPU_REQUEST: 500m  # ~33% of limit
```

**Recommendation:** Add CPU requests (typically 30-50% of limits):
```yaml
parameters:
  CPU_REQUEST_DATA_PRUNING: 300m
  CPU_REQUEST_EXPORTER: 300m
  # etc.
```

### 7.3 Resource Limit Comparison

#### API/Service Components

| Component | Notifications | RBAC | Host-Inventory | Tower-Analytics | Assessment |
|-----------|--------------|------|----------------|-----------------|------------|
| **Memory Limit** | 700Mi-1Gi | 1-2Gi | 2.5Gi | Not set (stage) | **MISSING** |
| **Memory Request** | 650-700Mi | 1Gi | 500Mi | Not set (stage) | **MISSING** |
| **CPU Limit** | 300m | 1 | 1.5 | 500m | OK |
| **CPU Request** | 150m | Not set | 500m | 300m | OK |
| **Replicas (Stage)** | 3 | 6 | 3-10 | 15 | High |
| **Replicas (Prod)** | 3 | 6 | 5-10 | 20 | High |

**Observation:** Tower-analytics has high replica counts but missing memory limits for stage.

#### Background Workers/Processors

| Component | Notifications Engine | RBAC Celery | Host-Inventory MQ | Tower-Analytics Processor | Assessment |
|-----------|---------------------|-------------|-------------------|--------------------------|------------|
| **Memory Limit** | 2Gi (stage), 16Gi (prod) | 2Gi | 2Gi | 2Gi (ephemeral), 4Gi (prod) | OK |
| **Memory Request** | 700Mi (stage), 8Gi (prod) | 512Mi | 500Mi | 1Gi (ephemeral), 2Gi (prod) | OK |
| **CPU Limit** | 1 | 700m-1 | 1 | 500m | **LOW** |

**Recommendation:** Consider increasing CPU limits for processor components:
```yaml
CPU_LIMIT_PROCESSOR_CONTROLLER: 1000m  # Increase from 500m
CPU_LIMIT_PROCESSOR_INGRESS: 1000m
```

### 7.4 Namespace Configuration Gaps

#### 7.4.1 Missing Namespace Labels

**Notifications namespace:**
```yaml
labels:
  service: notifications
  insights_cost_management_optimizations: "true"  # Cost tracking
```

**Tower-analytics namespace:**
```yaml
labels:
  service: tower-analytics
  # Missing: insights_cost_management_optimizations
```

**Recommendation:** Add cost management label if participating in cost optimization:
```yaml
labels:
  service: tower-analytics
  insights_cost_management_optimizations: "true"
```

#### 7.4.2 Missing Service Account Tokens

**Notifications namespace:**
```yaml
openshiftServiceAccountTokens:
- namespace:
    $ref: /openshift/appsrep11ue1/namespaces/app-sre-observability-per-cluster.yml
  serviceAccountName: integrations-cma
```

**Tower-analytics:** Not configured.

**Recommendation:** Add if you need cross-namespace service account access.

#### 7.4.3 Missing Certificate Management

**Notifications namespace:**
```yaml
- provider: rhcs-cert
  secret_name: it-services-cert
  service_account_name: hcc-notifications-production
  auto_renew_threshold_days: 60
```

**Tower-analytics:** Not configured.

**Recommendation:** Add if you use IT services certificates:
```yaml
- provider: rhcs-cert
  secret_name: automation-analytics-cert
  service_account_name: automation-analytics-production
  auto_renew_threshold_days: 60
  annotations:
    qontract.recycle: "true"
```

### 7.5 Health Check Configuration

#### Missing Probe Configuration

**Host-inventory:**
```yaml
INVENTORY_API_READS_LIVENESS_PROBE_PERIOD_SECONDS: 60
INVENTORY_API_READS_LIVENESS_PROBE_TIMEOUT_SECONDS: 120
INVENTORY_API_READS_READINESS_PROBE_PERIOD_SECONDS: 60
INVENTORY_API_READS_READINESS_PROBE_TIMEOUT_SECONDS: 120
```

**Notifications:**
```yaml
READINESS_INITIAL_DELAY: 40
LIVENESS_INITIAL_DELAY: 40
```

**Tower-analytics:** No explicit probe configuration.

**Recommendation:** Add probe configuration for reliability:
```yaml
parameters:
  READINESS_INITIAL_DELAY: 30
  LIVENESS_INITIAL_DELAY: 30
  READINESS_PROBE_PERIOD_SECONDS: 30
  LIVENESS_PROBE_PERIOD_SECONDS: 60
```

### 7.6 Job/CronJob Configuration

#### Suspension Flags Pattern

**Host-inventory uses suspension flags:**
```yaml
REAPER_SUSPEND: 'false'
FLOORIST_SUSPEND: 'false'
SP_VALIDATOR_SUSPEND: 'false'
PENDO_SYNCHER_SUSPEND: 'false'
```

**Tower-analytics:** No suspension flags for jobs.

**Recommendation:** Add suspension flags for operational control:
```yaml
parameters:
  DATA_PRUNING_SUSPEND: 'false'
  MSG_RECOVERY_SUSPEND: 'false'
  USER_METRICS_SUSPEND: 'false'
  ETL_PROCESSOR_LIGHTSPEED_SUSPEND: 'false'
```

This allows disabling jobs without code changes during incidents.

### 7.7 Summary: Configuration Gaps by Priority

#### Critical (Security/Reliability)

| Gap | Impact | Effort | Recommendation |
|-----|--------|--------|----------------|
| Missing `PGSSLMODE` | Security | Low | Add `verify-full` |
| No Kafka resilience params | Reliability | Low | Add retry/timeout params |
| Missing CPU requests | Resource planning | Medium | Add 30-50% of limits |

#### High (Observability)

| Gap | Impact | Effort | Recommendation |
|-----|--------|--------|----------------|
| No Sentry integration | Error tracking | Medium | Add DSN + enabled flag |
| No CloudWatch explicit | Log aggregation | Low | Add `CLOUDWATCH_ENABLED: true` |
| Missing probe config | Health monitoring | Low | Add probe timeouts |

#### Medium (Operations)

| Gap | Impact | Effort | Recommendation |
|-----|--------|--------|----------------|
| No job suspension flags | Incident response | Low | Add `*_SUSPEND` flags |
| Stale TODO comments | Maintainability | Low | Clean up or remove |
| Hardcoded dates | Maintenance burden | Medium | Use relative dates |
| Low Gunicorn processes | Performance | Low | Increase to 4 |

#### Low (Nice to Have)

| Gap | Impact | Effort | Recommendation |
|-----|--------|--------|----------------|
| No ElastiCache | Performance | High | Add if caching needed |
| No KEDA autoscaling | Cost optimization | High | Consider for variable load |
| No cost management label | Cost tracking | Low | Add label |

---

## Part 8: Additional Service Patterns (Extended Analysis)

This section covers patterns from additional services: sources, export-service, playbook-dispatcher, and vulnerability.

### 8.1 Component-Specific Resource Naming Patterns

**Best Practice from vulnerability service:**
```yaml
# Per-component resource definitions
CPU_REQUEST_WEBAPP: '250m'
CPU_LIMIT_WEBAPP: '500m'
MEMORY_REQUEST_WEBAPP: '800Mi'
MEMORY_LIMIT_WEBAPP: '1Gi'

CPU_REQUEST_MANAGER: '500m'
CPU_LIMIT_MANAGER: '1000m'
MEMORY_REQUEST_MANAGER: '1Gi'
MEMORY_LIMIT_MANAGER: '2Gi'

# Replicas per component
REPLICAS_WEBAPP: '3'
REPLICAS_MANAGER: '12'
REPLICAS_LISTENER: '3'
REPLICAS_EVALUATOR_UPLOAD: '3'
```

**Tower-analytics current pattern:**
```yaml
# Mixed naming - some follow pattern, some don't
MEMORY_REQUEST_ONEVIEW: 1Gi
MEMORY_LIMIT_ONEVIEW: 2Gi
CPU_LIMIT_PROCESSOR_CONTROLLER: 500m
# Missing: CPU_REQUEST_PROCESSOR_CONTROLLER
```

**Recommendation:** Standardize on `{METRIC}_{REQUEST|LIMIT}_{COMPONENT}` pattern and ensure all components have both request AND limit.

### 8.2 Job Configuration Patterns

**Best Practice from vulnerability service:**
```yaml
# Job scheduling via single parameter
JOBS: 'stale_systems:5,delete_systems:30,rules_git_sync:240,db_metrics:30,cacheman:5'

# Startup job sequencing
JOBS_STARTUP: 'db_metrics,cacheman,missing_refs'
```

**Best Practice from playbook-dispatcher:**
```yaml
# Job execution control
POPULATOR_RUN_NUMBER: '1'  # Increment to trigger job

# Connector pause control
CONNECTOR_PAUSE: 'false'
```

**Tower-analytics current pattern:**
```yaml
# Individual cron schedules (verbose)
CRON_SCHEDULE_MSG_RECOVERY: 0 */2 * * *
CRON_SCHEDULE_USER_METRICS: 0 10 * * *
CRON_SCHEDULE_DATA_PRUNING: 30 19 * * 4
```

**Assessment:** Tower-analytics pattern is fine but consider adding:
```yaml
# Job control flags (NEW)
MSG_RECOVERY_SUSPEND: 'false'
USER_METRICS_SUSPEND: 'false'
DATA_PRUNING_SUSPEND: 'false'

# Job version for manual triggers (NEW)
DATA_PRUNING_JOB_VERSION: '0'  # Increment to trigger
```

### 8.3 Feature Flag Patterns

**Best Practice from sources service:**
```yaml
# Disable patterns
DISABLED_APPLICATION_TYPES: 'type1,type2'  # Comma-separated list
DISABLE_RESOURCE_CREATION: 'false'
DISABLE_RESOURCE_DELETION: 'false'

# Skip patterns
SOURCE_TYPE_SKIP_LIST: 'skip1,skip2'
SKIP_EMPTY_SOURCES: 'true'
```

**Best Practice from vulnerability service:**
```yaml
# Enable patterns
ENABLE_UNLEASH: 'true'
ENABLE_PROFILER: 'true'  # Stage only
CW_ENABLED: 'TRUE'

# Suspend patterns
SUSPEND_CLUSTER: 'false'
FLOORIST_SUSPEND: 'false'
```

**Tower-analytics current pattern:**
```yaml
DATA_PRUNING_ENABLED: 'True'
DATA_EXPORT_ENABLED: 'True'
AUTO_HEALER_DRY_RUN: 'True'
```

**Recommendation:** Add operational control flags:
```yaml
# Operational controls (NEW)
PROCESSOR_CONTROLLER_SUSPEND: 'false'
PROCESSOR_INGRESS_SUSPEND: 'false'
EXPORTER_SUSPEND: 'false'
ROLLUPS_SUSPEND: 'false'

# Dry run controls (already have some)
AUTO_HEALER_DRY_RUN: 'True'  # Existing
DATA_PRUNING_DRY_RUN: 'false'  # NEW
```

### 8.4 Environment-Specific Configuration

**Best Practice from sources/vulnerability:**
```yaml
# Environment identifier
SOURCES_ENV: 'stage'  # or 'prod', 'perf'
VULNERABILITY_ENV: 'PROD'

# Environment-specific buckets
EXPORT_SERVICE_BUCKET: 'export-service-stage'  # Stage
EXPORT_SERVICE_BUCKET: 'export-service-prod'   # Prod
```

**Tower-analytics current pattern:**
```yaml
ENV_NAME: stage  # or prod
```

**Assessment:** Tower-analytics pattern is adequate.

### 8.5 Timeout and Buffer Configuration

**Best Practice from export-service:**
```yaml
# HTTP server timeouts
PUBLIC_HTTP_SERVER_READ_TIMEOUT: '30s'
PUBLIC_HTTP_SERVER_WRITE_TIMEOUT: '30s'
PRIVATE_HTTP_SERVER_READ_TIMEOUT: '30s'
PRIVATE_HTTP_SERVER_WRITE_TIMEOUT: '30s'

# Buffer sizes
AWS_UPLOADER_BUFFER_SIZE: '10485760'  # 10MB
AWS_DOWNLOADER_BUFFER_SIZE: '10485760'
```

**Best Practice from vulnerability:**
```yaml
# Pagination limits
MAXIMUM_PAGE_SIZE: '1000'

# Cache thresholds
CACHE_MINIMAL_ACCOUNT_SYSTEMS: '150'
```

**Tower-analytics:** Missing timeout/buffer configuration.

**Recommendation:** Add if applicable:
```yaml
# API timeouts (NEW)
API_READ_TIMEOUT: '30s'
API_WRITE_TIMEOUT: '60s'

# Processing limits (NEW)
MAX_BATCH_SIZE: '1000'
```

### 8.6 Go Runtime Configuration

**Best Practice from vulnerability (Go services):**
```yaml
# Go memory limit (80% of container limit)
GOMEMLIMIT: '4915MiB'  # For 6Gi container
```

**Tower-analytics:** Python-based, not applicable.

### 8.7 Kafka Connector Patterns

**Best Practice from playbook-dispatcher:**
```yaml
# Kafka connector configuration
KAFKA_SASL_MECHANISM: 'scram-sha-512'
NUM_REPLICAS: '3'  # Connector replicas
EVENT_CONSUMER_REPLICAS: '3'

# JVM settings for Kafka Connect
XMX: '3g'
XMS: '1g'

# Topic configuration
KAFKA_TOPIC_PREFIX: 'platform.'
```

**Tower-analytics current pattern:**
```yaml
KAFKA_GROUP_PROCESSOR_INGRESS: aa-processor-billing
```

**Recommendation:** Add Kafka resilience (already noted in Part 7).

### 8.8 Quota Patterns

**Best Practice from vulnerability:**
```yaml
# Separate quotas for terminating vs non-terminating
# Non-terminating (services):
limits: cpu: "24", memory: 24Gi
requests: cpu: "12", memory: 12Gi

# Terminating (jobs):
limits: cpu: "6", memory: 24Gi
requests: cpu: "3", memory: 12Gi
```

**Tower-analytics:** Has `tower-analytics-quota.yml` but should verify it has separate terminating/non-terminating quotas.

### 8.9 Floorist/Metrics Export Patterns

**Best Practice (common across services):**
```yaml
FLOORIST_SUSPEND: 'false'
FLOORIST_BUCKET_SECRET_NAME: 'insights-metrics-export-prod'
FLOORIST_DB_SECRET_NAME: 'automation-analytics-db'
FLOORIST_SCHEDULE: '0 */2 * * *'  # Every 2 hours
FLOORIST_QUERY_PREFIX: '/queries/'
FLOORIST_HMS_BUCKET_SECRET_NAME: 'hms-floorist-bucket'
```

**Tower-analytics:** Not using Floorist for metrics export.

**Recommendation:** Consider Floorist for standardized metrics export if not already using another solution.

### 8.10 Secret Version Tracking

**Best Practice (all mature services):**
```yaml
# In namespace files
- provider: vault-secret
  path: insights/secrets/insights-prod/tower-analytics-prod/django
  version: 1  # Track version
  annotations:
    qontract.recycle: "true"  # Enable rotation
```

**Tower-analytics:** Already following this pattern. ✅

### 8.11 Database Version Pinning

**Best Practice from sources:**
```yaml
# In namespace RDS configuration
overrides:
  engine_version: '15.12'  # Pin specific version
```

**Tower-analytics:** Using parameter group reference but should verify version pinning.

---

## Part 9: Konflux Configuration Deep-Dive

### 9.1 Shared vs Custom ECP Comparison

| Tenant | ECP Type | Policy Reference |
|--------|----------|------------------|
| aap-aa-tenant | Custom | `aap-aa` (tenant-specific) |
| rh-subs-watch-tenant | Shared | `rhtap-releng-tenant/app-interface-rh-subs-watch-prod` |
| insights-management-tenant | Shared | `rhtap-releng-tenant/consoledot-backend-standard` |
| hcc-platex-services-tenant | Shared | `rhtap-releng-tenant/app-interface-standard` |

**Recommendation:** Migrate to `app-interface-standard` or `consoledot-backend-standard`.

### 9.2 IntegrationTestScenario Comparison

| Feature | aap-aa-tenant | insights-management-tenant | Recommendation |
|---------|---------------|---------------------------|----------------|
| Test count | 8 | Varies by component | OK |
| SINGLE_COMPONENT | ❌ | ✅ | Add |
| Component contexts | ❌ | ✅ | Add |
| Optional label | ❌ | ✅ | Add for PR tests |
| Custom annotations | ✅ | ❌ | OK (unique to AA) |

### 9.3 ReleasePlan Comparison

| Feature | aap-aa-tenant | insights-management-tenant | Recommendation |
|---------|---------------|---------------------------|----------------|
| Separate stage/prod | ❌ | ✅ | Add |
| Auto-release (stage) | ✅ | ✅ | OK |
| Manual release (prod) | N/A | ✅ | Add |
| Enhanced releaseNotes | Partial | ✅ | Enhance |

### 9.4 ImageRepository Comparison

| Feature | aap-aa-tenant | insights-management-tenant | Recommendation |
|---------|---------------|---------------------------|----------------|
| SBOM notifications | ❌ | ✅ | **Add (HIGH)** |
| Mintmaker disabled | ❌ | ✅ | Add if needed |

---

## Appendix C: Full Parameter Comparison Matrix

### Deploy Configuration Parameters

| Parameter Category | Notifications | RBAC | Host-Inventory | Compliance | Tower-Analytics |
|-------------------|--------------|------|----------------|------------|-----------------|
| **Labels** |
| `dora` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `insights_cost_management_optimizations` | ✅ | ❌ | ❌ | ❌ | ❌ |
| **managedResourceTypes** |
| ClowdApp | ✅ | ✅ | ✅ | ✅ | ✅ |
| ClowdJobInvocation | ✅ | ✅ | ✅ | ❌ | ❌ |
| ConfigMap | ✅ | ❌ | ❌ | ❌ | ❌ |
| FloorPlan | ✅ | ❌ | ❌ | ❌ | ❌ |
| ScaledObject.keda.sh | ✅ | ❌ | ❌ | ❌ | ❌ |
| TriggerAuthentication.keda.sh | ✅ | ❌ | ❌ | ❌ | ❌ |
| KafkaConnector | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Observability** |
| Sentry | ✅ | ❌ | ❌ | ❌ | ❌ |
| CloudWatch explicit | ✅ | ❌ | ✅ | ❌ | ❌ |
| Dynatrace | ❌ | ❌ | ✅ | ❌ | ❌ |
| **Database** |
| PGSSLMODE | ❌ | ✅ | ✅ | ❌ | ❌ |
| Read replicas | ❌ | ❌ | ✅ | ❌ | ❌ |
| **Caching** |
| ElastiCache | ✅ | ❌ | ✅ | ✅ | ❌ |
| **Autoscaling** |
| MIN_REPLICAS | ✅ | ✅ | ✅ | ✅ | ❌ |
| MAX_REPLICAS | ❌ | ✅ | ❌ | ❌ | ❌ |
| KEDA | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Kafka** |
| Producer retries | ❌ | ❌ | ✅ | ❌ | ❌ |
| Consumer timeouts | ✅ | ❌ | ✅ | ❌ | ❌ |
| **Health Checks** |
| Probe configuration | ✅ | ❌ | ✅ | ❌ | ❌ |
| **Operations** |
| Job suspension flags | ❌ | ❌ | ✅ | ✅ | ❌ |
| Dry run flags | ❌ | ❌ | ✅ | ❌ | ❌ |

---

## Appendix D: Recommended Configuration Template

Based on the analysis of 12+ services and 4+ Konflux tenants, here's a comprehensive recommended configuration template for tower-analytics:

### D.1 deploy-clowder.yml Changes

```yaml
# Header changes
labels:
  service: tower-analytics
  platform: insights
  dora: insights-production  # NEW - DORA metrics

managedResourceTypes:
- ClowdApp
- ClowdJobInvocation  # NEW - if using CronJobs
- Service
- Frontend

# Stage target parameter additions
parameters:
  # === SECURITY (CRITICAL) ===
  PGSSLMODE: 'verify-full'  # NEW - enforce SSL

  # === OBSERVABILITY (HIGH) ===
  SENTRY_DSN: ${SENTRY_DSN}  # NEW
  SENTRY_ENABLED: 'true'  # NEW
  CLOUDWATCH_ENABLED: 'true'  # NEW - explicit
  LOG_LEVEL: 'DEBUG'  # Stage only

  # === KAFKA RESILIENCE (HIGH) ===
  KAFKA_PRODUCER_RETRIES: '8'  # NEW
  KAFKA_PRODUCER_RETRY_BACKOFF_MS: '250'  # NEW
  KAFKA_CONSUMER_SESSION_TIMEOUT_MS: '15000'  # NEW
  KAFKA_CONSUMER_HEARTBEAT_INTERVAL_MS: '5000'  # NEW

  # === HEALTH CHECKS (HIGH) ===
  READINESS_INITIAL_DELAY: '30'  # NEW
  LIVENESS_INITIAL_DELAY: '30'  # NEW
  READINESS_PROBE_PERIOD_SECONDS: '30'  # NEW
  LIVENESS_PROBE_PERIOD_SECONDS: '60'  # NEW

  # === JOB CONTROL (MEDIUM) ===
  DATA_PRUNING_SUSPEND: 'false'  # NEW
  MSG_RECOVERY_SUSPEND: 'false'  # NEW
  USER_METRICS_SUSPEND: 'false'  # NEW
  ETL_PROCESSOR_LIGHTSPEED_SUSPEND: 'false'  # NEW

  # === PERFORMANCE (MEDIUM) ===
  GUNICORN_PROCESSES: 4  # UPDATE from 1

  # === RESOURCE REQUESTS (MEDIUM) ===
  CPU_REQUEST_DATA_PRUNING: '150m'  # NEW - 30% of limit
  CPU_REQUEST_EXPORTER: '150m'  # NEW
  CPU_REQUEST_PROCESSOR_CONTROLLER: '150m'  # NEW
  CPU_REQUEST_PROCESSOR_INGRESS: '150m'  # NEW

  # === AUTOSCALING (LOW) ===
  MIN_REPLICAS_API: 10  # NEW
  MAX_REPLICAS_API: 25  # NEW

# Prod target additions
- namespace:
    $ref: /services/insights/tower-analytics/namespaces/tower-analytics-prod.yml
  ref: <sha>
  parameters:
    # ... existing params ...

    # === REMOVE STALE PARAMS ===
    # BUNDLES_BUCKET_NAME: insights-ingress-prod # REMOVE - not used
    # BUNDLES_SECRET_NAME: upload-s3 # REMOVE - not used

    # === ADD NEW PARAMS ===
    PGSSLMODE: 'verify-full'
    SENTRY_DSN: ${SENTRY_DSN}
    SENTRY_ENABLED: 'true'
    LOG_LEVEL: 'INFO'  # Prod uses INFO

    # === FIX HARDCODED DATES ===
    # UNPROCESSED_EVENTS_MIN_DATE: '2023-10-25'  # REMOVE - stale
    UNPROCESSED_EVENTS_LOOKBACK_DAYS: '90'  # NEW - rolling window

  promotion:
    publish:
    - automation-analytics-prod-deploy-success-channel  # NEW
```

### D.2 Konflux Configuration Changes

#### ir-aap-aa.yml (ImageRepository) - Add SBOM Notifications
```yaml
apiVersion: appstudio.redhat.com/v1alpha1
kind: ImageRepository
metadata:
  name: aap-aa
spec:
  # ... existing config ...
  notifications:  # NEW - CRITICAL
    - config:
        url: https://bombino.api.redhat.com/v1/sbom/quay/push
      event: repo_push
      method: webhook
      title: SBOM-event-to-Bombino
```

#### IntegrationTestScenario - Use Shared Policy
```yaml
# In its-aap-aa-*.yml files
spec:
  params:
    - name: POLICY_CONFIGURATION
      value: rhtap-releng-tenant/app-interface-standard  # CHANGE from aap-aa
    - name: SINGLE_COMPONENT  # NEW
      value: 'true'
```

#### Separate Stage/Prod ReleasePlans
```yaml
# rp-aap-aa-stage.yml (NEW)
apiVersion: appstudio.redhat.com/v1alpha1
kind: ReleasePlan
metadata:
  name: aap-aa-stage
  labels:
    release.appstudio.openshift.io/auto-release: "true"
    release.appstudio.openshift.io/standing-attribution: "true"
    release.appstudio.openshift.io/releasePlanAdmission: "aap-aa-stage"
spec:
  application: aap-aa
  target: rhtap-releng-tenant

# rp-aap-aa-prod.yml (MODIFY existing)
metadata:
  labels:
    release.appstudio.openshift.io/auto-release: "false"  # Manual for prod
```

### D.3 Namespace Configuration Changes

```yaml
# In tower-analytics-prod.yml namespace
labels:
  service: tower-analytics
  insights_cost_management_optimizations: "true"  # NEW - cost tracking
```

### D.4 Parameter Removal Checklist

| Parameter | Location | Reason |
|-----------|----------|--------|
| `BUNDLES_BUCKET_NAME: insights-ingress-prod` | Prod | Unused (TODO comment) |
| `BUNDLES_SECRET_NAME: upload-s3` | Prod | Unused (TODO comment) |
| `UNPROCESSED_EVENTS_MIN_DATE: '2023-10-25'` | Prod | Stale date (2+ years old) |
| `AMPLITUDE_ETL_END_DATE: '2025-03-05'` | Stage | Stale date |

### D.5 Boolean Standardization

Change all boolean strings to lowercase for consistency:
```yaml
# Before (inconsistent)
RBAC_ENABLED: 'True'
LOCK_MESSAGES_RECOVERY_ENABLED: 'true'
AUTO_HEALER_DRY_RUN: 'True'

# After (consistent)
RBAC_ENABLED: 'true'
LOCK_MESSAGES_RECOVERY_ENABLED: 'true'
AUTO_HEALER_DRY_RUN: 'true'
```

---

## Appendix E: Services Analyzed

| Service | Type | Key Patterns Extracted |
|---------|------|----------------------|
| notifications | Mature | Sentry, KEDA, DORA, promotion gates |
| rbac | Mature | PGSSLMODE, Celery, autoscaling |
| host-inventory | Data-heavy | Read replicas, Kafka tuning, Dynatrace |
| compliance | Mature | ElastiCache, job suspension |
| sources | Mature | Component resources, feature flags |
| export-service | Simple | Timeout configuration, buffer sizes |
| playbook-dispatcher | Worker-heavy | Kafka connector, JVM settings |
| vulnerability | Complex | 15+ components, Go runtime, quotas |
| rh-subs-watch-tenant | Konflux | Shared ECP policy |
| insights-management-tenant | Konflux | SBOM, component testing, stage/prod plans |
| hcc-platex-services-tenant | Konflux | Shared ECP policy |
| rhdh-tenant | Konflux | Version-specific releases |
| rhoai-tenant | Konflux | ProjectDevelopmentStream |

---

*Report generated by SaaS Configuration Analyzer*
*Deep-dive analysis completed: 2026-01-29*
*Services analyzed: 12+ App-Interface, 5+ Konflux tenants*
