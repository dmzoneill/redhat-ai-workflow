---
title: "ANSTRAT-1500: Support Data Export to Dataverse for Ansible Cloud Analytics"
---

|                           |                                               |
| ------------------------- | --------------------------------------------- |
| **Date**                  | 2026-03-06                                    |
| **Component**             | automation-analytics, analytics-hcc-service   |
| **Authors**               | David O Neill                                 |
| **Supersedes**            | NA                                            |
| **Superseded By**         | NA                                            |
| **Feature / Initiative**  | [ANSTRAT-1500](https://issues.redhat.com/browse/ANSTRAT-1500) |
| **Implementation Epic**   | [AAP-53376](https://issues.redhat.com/browse/AAP-53376) (Dataverse ELT Migration - Snowpipe and dbt) |
| **Links**                 | [Handbook SDP PR #1243](https://github.com/ansible/handbook/pull/1243), [Dataverse integration repo (notes)](https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration), [app-interface Lambda MR !176223](https://gitlab.cee.redhat.com/service/app-interface/-/merge_requests/176223), [Slack #wg-aap-analytics-dataverse-integration](https://redhat.enterprise.slack.com/archives/C0AB2M3K02K) |

## What

This SDP establishes the requirements and design for exporting Ansible Analytics data to Red Hat's enterprise Dataverse platform (Snowflake), restoring paused Tableau reports and aligning with Red Hat-wide Dataverse adoption by end of CY25. Automation Analytics Tableau reports have been paused since Q4 2025 due to RedShift end-of-life and schema incompatibility; this initiative delivers an ELT (Extract, Load, Transform) pipeline from the Analytics HCC service to Snowflake via Snowpipe and dbt.

**Current state:** RedShift-based data warehouse; Airflow-managed ETL; Tableau reports paused.

**Target architecture:**
```
AAP Metrics → S3 Export → Dedicated S3 Buckets → SQS → Lambda → DDS S3 → Snowpipe → Snowflake/Dataverse → dbt → Tableau
```

**Key decisions (from refinement notes):**
- **ELT confirmed:** Extract from current DB/S3 → Load into Snowflake first (Snowpipe) → Transform in Snowflake (dbt). No ETL in AAP.
- **Raw data only:** JSON in Snowpipe bucket; five sources (Tower, Billing, Lightspeed, Hub, EDA). No Parquet; no rollup re-uploads.
- **Lambda replication:** Direct replication via Lambda from dedicated AA S3 buckets to DDS S3; platform requires data in a single subfolder in shared S3 — Lambda is required and maintained by platform team.
- **Two-phase POC:** Phase 1 = one table loaded via Snowpipe (E&L); Phase 2 = dbt transform to Nabo's schema (T). Timeline ~2 months.
- **Support model:** Automation Analytics is an HCC product; support from APPSRE (ingress, S3/SQS; Lambda support limited) and Dataverse (Snowflake, Snowpipe). Every component must have a clear support owner; request Dataverse SDP and formal sign-off.

## Why

- **Business:** Tableau reports paused since Q4 2025; sales and partner teams (TeleSense) lack operational reporting; urgent need to restore reporting and align with enterprise data strategy.
- **Technical:** RedShift end-of-life; current S3 → RedShift pipeline incompatible with Dataverse; move from ETL (Airflow) to ELT (Snowflake-native) for scale and cost.
- **Strategic:** Red Hat-wide consolidation to Dataverse by end of CY25; operational efficiency and scalability for growing AAP customer base.

## Requirements

- R1: Data from Automation Analytics (ingress tarballs) must be loaded into Snowflake via a repeatable, event-driven pipeline (Snowpipe with `autoingest=true`).
- R2: Pipeline must support four environments (prod, pre-prod, stage, dev/sandbox) with dedicated S3 buckets and Lambda replication to DDS S3.
- R3: Transform layer (dbt) must produce schema-compatible outputs for Tableau restoration with &lt;0.1% variance from historical RedShift data.
- R4: Credentials and configuration must be managed via app-interface (Vault `snowflake` secret); no Clowder ObjectBuckets for Snowflake.
- R5: Pipeline must be observable (Prometheus metrics, DLQ for Lambda failures); non-blocking (upload failures must not block Kafka or RECOVERY).
- R6: Architecture and support boundaries must be validated with APPSRE and Dataverse before production deployment; Dataverse SDP and change-approval process requested.

## Problem Statements

### P1: BLOCKING — How do we establish and validate the data pipeline from Analytics HCC to Snowflake within APPSRE and Dataverse support boundaries?

Architecture uses dedicated S3 buckets in AA accounts, Lambda (event-driven via SQS) for replication to DDS S3 in account 654654343825, then Snowpipe into Snowflake. Lambda is required by platform (single subfolder in shared bucket); APPSRE Lambda support is limited. ATLAN access must be resolved before sending test data. Dataverse architect meeting and formal SDP/sign-off from both APPSRE and Dataverse are blocking before Lambda MR !176223 merge and production enablement.

**Status:** In progress. Snowpipe pipeline built (MR !1511); Lambda implemented (MR !176223); cross-account bucket policies and support validation pending.

### P2: BLOCKING — How do we validate end-to-end that data in Snowflake matches historical RedShift and supports Tableau restoration?

Phase 1 validates one table loaded via Snowpipe. Phase 2 validates dbt output against Nabo's schema and &lt;0.1% variance from RedShift; TeleSense consumes for Tableau restoration. Test plan to be created and signed off (PM, EM, SWEs, SQEs).

**Status:** Phase 1 in progress (AAP-64892); Phase 2 (AAP-64893) and test plan pending.

### P3: How do we ensure security and compliance for cross-account S3, Lambda, and Snowflake credentials?

Cross-account S3 (Lambda in insights accounts writing to dataverse buckets); Vault credentials; ProdSec/Thomas Eagle consultation to be completed and documented. Support boundaries and escalation to be defined in SDP.

**Status:** Security assessment (refinement task AAP-59163) pending.

## Support Model and Governance

- **APPSRE:** OpenShift, ingress, S3/SQS. Lambda support **limited** (accepted but not core managed service).
- **Dataverse:** Snowflake, Snowpipe, data product config. Service contracts still maturing; architecture evolved during design.
- **Guiding principle:** Do not build components neither APPSRE nor Dataverse will support. Request Dataverse SDP documentation and architectural change approval process; define SLI/SLO for Snowpipe ingestion and cross-account replication; establish incident response with both parties.

## Implementation Progress (AAP-53376)

- **Done:** Snowpipe ingestion pipeline (MR !1511); 94 dbt staging + 6 mart models (MR !5); Vault credentials (MR !175083); Lambda S3 sync via terraform-repo (MR !176223).
- **Pending:** Lambda MR merge; cross-account bucket policies; AppSRE Bot (devtools-bot) Reporter on dataverse-terraform-lambda; stage validation; Dataverse SDP and support alignment.

## References

- **Refinement plan:** [AAP-59158 refinement plan](https://gitlab.cee.redhat.com/automation-analytics/redhat-ai-workflow/-/blob/main/docs/meetings/AAP-59158-dataverse-refinement-plan.md).
- **Notes and context:** [dataverse-integration](https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration) ([summary](https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration/-/blob/main/summary.md), [docs](https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration/-/tree/main/docs), [entries](https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration/-/tree/main/entries)).
- **Jira:** ANSTRAT-1500 (Feature), AAP-53376 (Epic), AAP-64892 (POC Phase 1), AAP-64893 (POC Phase 2), AAP-65345 (ingress), AAP-66507 (Lambda).
