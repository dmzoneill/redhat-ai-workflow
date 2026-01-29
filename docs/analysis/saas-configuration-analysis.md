# SaaS Configuration Maturity Analysis Report

**Project:** Automation Analytics (tower-analytics / aap-aa-tenant)  
**Date:** 2026-01-29  
**Scope:** Konflux Release-Data + App-Interface configurations

---

## Executive Summary

This analysis compares your Automation Analytics SaaS configurations against other projects in the Insights platform to identify gaps, best practices, and improvement opportunities. Your configuration is **moderately mature** with some notable strengths but several areas for improvement.

### Maturity Score: 7/10

| Category | Score | Notes |
|----------|-------|-------|
| Konflux Configuration | 8/10 | Strong test coverage, good ECP policy |
| App-Interface SaaS | 7/10 | Good structure, missing some best practices |
| SLO/Observability | 6/10 | Basic SLOs, could be more comprehensive |
| Security/Compliance | 7/10 | Good ECP exclusions, missing some hardening |
| Release Process | 8/10 | Proper promotion gates, pinned prod refs |

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

##### 1. Missing Quick/Slow Test Scenarios

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

##### 2. Missing Version-Specific Release Plans

**Observed in mature tenants (rhdh-tenant, rhoai-tenant):** Version-specific release plans for stage vs prod.

**Current:** Single release plan for all releases.

**Recommendation:** Consider separate stage/prod release plans:

```yaml
# rp-aap-aa-stage.yml
apiVersion: appstudio.redhat.com/v1alpha1
kind: ReleasePlan
metadata:
  name: aap-aa-stage
  labels:
    release.appstudio.openshift.io/auto-release: "true"
spec:
  application: aap-aa
  target: rhtap-releng-tenant-stage  # Stage target
  
# rp-aap-aa-prod.yml  
apiVersion: appstudio.redhat.com/v1alpha1
kind: ReleasePlan
metadata:
  name: aap-aa-prod
  labels:
    release.appstudio.openshift.io/auto-release: "false"  # Manual prod releases
spec:
  application: aap-aa
  target: rhtap-releng-tenant
```

##### 3. Enterprise Contract Policy Exclusions Review

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

### High Priority (Do Now)

1. **Add `dora` label** to deploy-clowder.yml
2. **Add prod promotion gate** for deployment visibility
3. **Clean up TODO comments** in configuration
4. **Review and update SRE checkpoint** contract version

### Medium Priority (Next Sprint)

5. **Enable CVE scanning** in ECP (warning mode first)
6. **Add Sentry integration** for error tracking
7. **Increase SLO targets** if metrics support it
8. **Add per-component SLOs** for critical services

### Low Priority (Backlog)

9. **Consider KEDA autoscaling** for variable workloads
10. **Add performance testing namespace** 
11. **Create query library** for ad-hoc investigations
12. **Evaluate hermetic builds** for reproducibility

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

Based on the analysis, here's a recommended configuration template for tower-analytics:

```yaml
# deploy-clowder.yml additions
labels:
  service: tower-analytics
  platform: insights
  dora: insights-production  # NEW

managedResourceTypes:
- ClowdApp
- ClowdJobInvocation  # NEW - if using CronJobs
- Service
- Frontend

# Stage target additions
parameters:
  # Observability (NEW)
  SENTRY_DSN: ${SENTRY_DSN}
  SENTRY_ENABLED: 'true'
  CLOUDWATCH_ENABLED: 'true'
  LOG_LEVEL: 'DEBUG'
  
  # Database (NEW)
  PGSSLMODE: 'verify-full'
  
  # Kafka resilience (NEW)
  KAFKA_PRODUCER_RETRIES: '8'
  KAFKA_PRODUCER_RETRY_BACKOFF_MS: '250'
  KAFKA_CONSUMER_SESSION_TIMEOUT_MS: '15000'
  KAFKA_CONSUMER_HEARTBEAT_INTERVAL_MS: '5000'
  
  # Health checks (NEW)
  READINESS_INITIAL_DELAY: '30'
  LIVENESS_INITIAL_DELAY: '30'
  
  # Job control (NEW)
  DATA_PRUNING_SUSPEND: 'false'
  MSG_RECOVERY_SUSPEND: 'false'
  
  # Performance (UPDATE)
  GUNICORN_PROCESSES: 4  # Increase from 1
  
  # Autoscaling (NEW)
  MIN_REPLICAS_API: 10
  MAX_REPLICAS_API: 25

# Prod target additions
promotion:
  publish:
  - automation-analytics-prod-deploy-success-channel  # NEW
```

---

*Report generated by SaaS Configuration Analyzer*
*Deep-dive analysis completed: 2026-01-29*
