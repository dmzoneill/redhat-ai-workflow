# Jira description updates for AAP-67712 and AAP-67713

## AAP-67712 — Create Lambda functions for S3-to-Dataverse Snowpipe copy

**Purpose**
Register and deploy the Dataverse Snowpipe Lambda via app-interface so that Terraform is executed in the correct AWS accounts and the Lambda functions exist in stage and prod.

**Scope**
* app-interface: Add or update repo definitions for the dataverse-terraform-lambda Terraform repo in insights-stage and insights-prod.
* Repo definitions: `data/aws/insights-stage/repos/tower-analytics-dataverse-lambda.yml` and `data/aws/insights-prod/repos/tower-analytics-dataverse-lambda.yml`.
* Each file specifies: repository URL, ref (Git SHA to deploy), projectPath (`stage` or `prod`), tfVersion, account ref, app ref.
* Terraform is not run manually; the app-interface terraform-repo integration (Tekton pipelines) clones the repo at the given ref and runs Terraform in the selected projectPath.
* Secrets for Terraform execution: AWS credentials and backend state come from Vault (account automationToken) and app-interface state.yml; no secrets stored in app-interface YAML.
* Outcome: Lambda functions exist in AWS (insights-stage and insights-prod) and are triggered by S3 events via SQS.

**Out of scope**
* Writing or changing the Lambda Python code or Terraform module code (see sibling story AAP-67713).
* Creating the dataverse-terraform-lambda repository or its initial codebase.

**References**
* Epic: AAP-53376
* Study: docs/meetings/dataverse-terraform-lambda-app-interface-study.md (in redhat-ai-workflow)
* app-interface: data/aws/insights-{stage|prod}/repos/tower-analytics-dataverse-lambda.yml, account.yml, state.yml

**Acceptance criteria**
* Repo definitions for tower-analytics-dataverse-lambda exist for both insights-stage and insights-prod with correct repository URL and ref.
* After merging app-interface changes, terraform-repo pipelines run successfully and Lambda functions are created/updated in the correct AWS accounts.
* Lambda configuration (batch size, timeout, destination buckets) is as defined in the Terraform repo (stage vs prod); no app-interface-specific overrides required beyond ref and projectPath.

**Definition of done**
* Code reviewed and merged in app-interface.
* Terraform apply successful for stage and prod (or documented follow-up to fix any failures).

---

## AAP-67713 — Create dataverse-terraform-lambda repository and Lambda code

**Purpose**
Implement the Terraform repo and Lambda runtime code that copy objects from Tower Analytics Snowpipe S3 buckets to Dataverse destination S3 buckets (S3 → SQS → Lambda → destination buckets).

**Scope**
* Repository: dataverse-terraform-lambda (e.g. under automation-analytics group).
* Lambda function code: Python handler that reads SQS messages (S3 event notifications), copies objects from source bucket to one or more destination buckets with configurable prefix mapping; supports same-account and cross-account copy (multipart for large objects).
* Terraform module: e.g. modules/lambda-s3-sync — S3 bucket event notifications, SQS queue, Lambda (IAM role, env vars, batch size, timeout), DLQ for failed messages.
* Per-environment config: stage/main.tf and prod/main.tf defining source bucket, source prefix filter, destination buckets and prefixes, batch size (e.g. 50 stage, 1000 prod), timeout (e.g. 900s prod).
* Build/deploy: Lambda zip artifact built and referenced from Terraform; Terraform state in S3 via app-interface terraform-repo (handled in sibling story AAP-67712).
* Documentation: README with verification steps, how to verify write access to target buckets (test upload, CloudWatch, cross-account bucket policy).

**Data flow**
* S3 PutObject (source bucket) → S3 event notification → SQS (batch window 30s, batch size 10) → Lambda → copy to each destination bucket (key/prefix mapping per DEST_BUCKETS env).
* Failed messages (after retries) → Dead Letter Queue.
* No secrets at Lambda runtime; IAM role only. DEST_BUCKETS and LOG_LEVEL from Terraform env.

**Out of scope**
* app-interface repo definitions and terraform-repo pipeline runs (see sibling story AAP-67712).
* Creating or modifying source Snowpipe buckets; only consuming their events and copying to configured destination buckets.

**References**
* Epic: AAP-53376
* Sibling story: AAP-67712 (Lambda functions / app-interface deployment)
* Study: docs/meetings/dataverse-terraform-lambda-app-interface-study.md

**Acceptance criteria**
* Repo exists with Lambda Python code, Terraform module, and stage/prod Terraform configs.
* Lambda copies objects from configured source prefix to each destination bucket with correct prefix mapping.
* Batch size and timeout set per environment (e.g. 50 / 1000 batch, 900s timeout prod).
* README documents how to verify deployment and write access to target buckets (including cross-account).

**Definition of done**
* Code reviewed and merged.
* Tests pass (if any); deployment and verification steps documented and validated.
