# Dataverse Terraform Lambda ↔ App-Interface: Usage, Data Flow, and Secrets

Study of how **dataverse-terraform-lambda** relates to **app-interface**, how the Lambdas copy data to target buckets, and how secrets reach the system.

---

## 1. Relationship: dataverse-terraform-lambda ↔ app-interface

### 1.1 What app-interface does

- **Owns deployment**: The Lambda Terraform is **not** run manually. It is run by the **app-interface terraform-repo** integration.
- **Repo registration**: app-interface declares the Terraform repo per AWS account and tells the executor which ref to run and which subdirectory (`stage` / `prod`).

### 1.2 App-interface files involved

| File | Purpose |
|------|---------|
| `data/aws/insights-stage/repos/tower-analytics-dataverse-lambda.yml` | Stage: repo URL, ref, `projectPath: stage` |
| `data/aws/insights-prod/repos/tower-analytics-dataverse-lambda.yml` | Prod: repo URL, ref, `projectPath: prod` |
| `data/aws/insights-stage/account.yml` | Stage AWS account (uid, automationToken Vault path, terraformState) |
| `data/aws/insights-prod/account.yml` | Prod AWS account (same) |
| `data/aws/insights-stage/state.yml` | Terraform backend S3 bucket + key for terraform-repo |
| `data/aws/insights-prod/state.yml` | Same for prod |
| `data/services/insights/tower-analytics/app.yml` | Tower Analytics app; lists `dataverse-terraform-lambda` as code component |

### 1.3 Repo definition (per environment)

```yaml
# insights-stage/repos/tower-analytics-dataverse-lambda.yml
$schema: /aws/terraform-repo-1.yml
account:
  $ref: /aws/insights-stage/account.yml
app:
  $ref: /services/insights/tower-analytics/app.yml
name: tower-analytics-dataverse-lambda-stage
repository: https://gitlab.cee.redhat.com/automation-analytics/dataverse-terraform-lambda
ref: <sha>   # e.g. 503bc8cba99e7057eb18e01f63675ee74d0ff859
projectPath: stage
tfVersion: "1.5.7"
```

- **projectPath** selects which root (e.g. `stage/` or `prod/`) the executor runs (`terraform -chdir=stage` / `-chdir=prod`).
- **Deploying a new version**: Update `ref` in both YAML files to the desired Git SHA, then merge to app-interface; terraform-repo pipelines will run and apply.

### 1.4 How terraform-repo runs this repo

- The **terraform-repo** integration (Tekton pipelines in app-interface) runs the **terraform-repo executor**.
- The executor:
  - Clones app-interface and the Terraform repo (at the given `ref`).
  - Resolves the AWS **account** (insights-stage / insights-prod) and its **automationToken** (Vault path).
  - Uses **terraform state** config from `state.yml` (S3 backend bucket + key for `integration: terraform-repo`).
  - Runs Terraform in the repo’s `projectPath` with credentials from Vault (see “Secrets” below).

---

## 2. How the Lambdas copy data to target buckets

### 2.1 High-level flow

```
S3 PutObject (source bucket)
    → S3 event notification
    → SQS queue (batch window 30s, batch size 10)
    → Lambda invocation
    → Lambda copies object to each destination bucket (same key/prefix mapping)
    → Failed messages (after 3 retries) → Dead Letter Queue
```

- **No polling**: Event-driven only.
- **Copy mechanism**: Lambda uses **S3 copy** (same-account or cross-account depending on bucket ownership): `s3.copy_object` for objects &lt; 5 GB, multipart copy for larger.

### 2.2 Per-environment mapping

| Env   | Lambda name                              | Source bucket                      | Destination buckets |
|-------|------------------------------------------|------------------------------------|----------------------|
| Stage | `aapautomationanalytics-dev-sandbox-sync` | `tower-analytics-snowpipe-stage-s3` | `dataverse-dev-snowpipe`, `dataverse-sandbox-snowpipe` |
| Prod  | `aapautomationanalytics-prod-preprod-sync` | `tower-analytics-snowpipe-prod`     | `dataverse-prod-snowpipe`, `dataverse-preprod-snowpipe` |

### 2.3 Source prefix (filter)

- **Stage**: `source_prefix = "source-stage-aapautomationanalytics/"` — only objects under this prefix trigger the Lambda.
- **Prod**: `source_prefix = "source-prod-aapautomationanalytics/"`.

### 2.4 Destination key mapping

Configured in Terraform as `dest_buckets_with_prefixes` and passed to the Lambda as the **DEST_BUCKETS** env var (JSON map bucket → prefix).

- **Stage**:
  - `dataverse-dev-snowpipe`     → prefix `source-dev-aapautomationanalytics/`
  - `dataverse-sandbox-snowpipe` → prefix `source-sandbox-aapautomationanalytics/`
- **Prod**:
  - `dataverse-prod-snowpipe`    → prefix `source-prod-aapautomationanalytics/`
  - `dataverse-preprod-snowpipe` → prefix `source-preprod-aapautomationanalytics/`

The Lambda keeps the object path under the source prefix and writes it under the corresponding destination prefix (see `lambda_function.py`: `dst_key = f"{dst_prefix.rstrip('/')}/{src_key.split('/', 1)[-1]}"`).

### 2.5 Where buckets live

- **Source buckets**: In the same AWS account as the Lambda (insights-stage / insights-prod); created by other app-interface resources (e.g. tower-analytics namespaces with externalResources for `tower-analytics-snowpipe-s3`).
- **Destination buckets**: Names suggest they may be in the **Dataverse** account (e.g. 654654343825 referenced elsewhere in app-interface for `dataverse-*-snowpipe`). For cross-account copy, the **destination bucket policy** must allow the Lambda’s IAM role (from the Insights account) to `s3:PutObject` etc. The Terraform only grants the Lambda role access to `arn:aws:s3:::destination_bucket/*`; the other account’s bucket policy must permit that role.

---

## 3. How secrets get to the system

There are two separate concerns: **Terraform execution** (who runs Terraform and how they authenticate) and **Lambda runtime** (what the Lambda uses to access S3).

### 3.1 Secrets for Terraform execution (app-interface → Terraform)

Terraform needs:

- **AWS provider credentials** (`access_key`, `secret_key`, `region`) to run in insights-stage or insights-prod.
- **Backend credentials** to read/write Terraform state in S3.

These are **not** stored in app-interface YAML. They come from:

- **Account `automationToken`** in app-interface:
  - **insights-stage**: `path: insights/creds/terraform/config-stage`, `field: all`, `version: 8`
  - **insights-prod**: `path: insights/creds/terraform/config-prod`, `field: all`, `version: 6`
- The **terraform-repo executor** (running in OpenShift with access to Vault) fetches this token and passes the credentials into Terraform (e.g. as `TF_VAR_access_key`, `TF_VAR_secret_key`, `TF_VAR_region` or equivalent).
- The **backend** is configured via app-interface’s **state** files: S3 bucket and key for the `terraform-repo` integration. Backend credentials are typically the same AWS creds or an identity the executor already has.

So: **secrets for Terraform** = Vault (`insights/creds/terraform/config-{stage|prod}`) → executor → Terraform.

### 3.2 “Secrets” for the Lambda (runtime)

The Lambda **does not receive any injected secrets**.

- It runs with an **IAM role** created by the same Terraform (`aws_iam_role.lambda_exec` + `aws_iam_role_policy.s3_access` and `sqs_access`).
- That role has:
  - **Read**: source bucket (e.g. `tower-analytics-snowpipe-stage-s3` / `tower-analytics-snowpipe-prod`).
  - **Write**: destination buckets (e.g. `dataverse-dev-snowpipe`, `dataverse-sandbox-snowpipe`, etc.).
  - **SQS**: receive/delete messages from the events queue.
- The only “config” the Lambda gets is **environment variables** set by Terraform:
  - **DEST_BUCKETS**: JSON map of destination bucket name → prefix (non-secret).
  - **LOG_LEVEL**: optional.

So: **no secrets to the Lambdas** — they use IAM only; destination bucket names and prefixes are non-secret configuration.

### 3.3 Summary table

| What | Where it comes from |
|------|---------------------|
| Terraform AWS creds (run Terraform) | Vault `insights/creds/terraform/config-{stage\|prod}` via account `automationToken` |
| Terraform backend (state) | app-interface `state.yml` (S3 bucket + key) |
| Lambda S3 access | IAM role created by Terraform; no secrets |
| Lambda config (buckets/prefixes) | Env var `DEST_BUCKETS` set by Terraform from `dest_buckets_with_prefixes` |

---

## 4. References

- **dataverse-terraform-lambda**: `README.md`, `lambda_function.py`, `modules/lambda-s3-sync/main.tf`, `stage/main.tf`, `prod/main.tf`, `stage/providers.tf`, `prod/providers.tf`
- **app-interface**:
  - `data/aws/insights-stage/repos/tower-analytics-dataverse-lambda.yml`
  - `data/aws/insights-prod/repos/tower-analytics-dataverse-lambda.yml`
  - `data/aws/insights-stage/account.yml`, `state.yml`
  - `data/aws/insights-prod/account.yml`, `state.yml`
  - `data/services/insights/tower-analytics/app.yml`
  - `data/services/app-interface/terraform-repo/` (terraform-repo integration)
- **Tower Analytics snowpipe buckets**: e.g. `stage-tower-analytics-stage.yml` / `tower-analytics-prod.yml` externalResources for `tower-analytics-snowpipe` (source buckets).
- **Jira**: AAP-66507 / Epic AAP-53376 (from dataverse-terraform-lambda README).
