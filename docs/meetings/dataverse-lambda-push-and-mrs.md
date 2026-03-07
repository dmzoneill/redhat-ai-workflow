# Push branches and create MRs for dataverse-terraform-lambda + app-interface

Run these on your machine (VPN on so `gitlab.cee.redhat.com` resolves).

## 1. dataverse-terraform-lambda

```bash
cd /home/daoneill/src/dataverse-terraform-lambda
git push -u origin fix/batch-sizes-and-timeout
```

Then create the MR (GitLab UI or glab):

- **Source branch:** `fix/batch-sizes-and-timeout`
- **Target:** `main`
- **Title:** `fix: batch 50 stage, 1000 prod; prod timeout 900s`
- **Description:** Batch sizes and timeout for S3 sync Lambda. Stage: 50. Prod: 1000, timeout 900s. Merge this first, then merge the app-interface MR so terraform-repo picks up the new ref.

**Commit SHA (already used in app-interface):** `80fe8144774c1b08c7bde41e6f78a515591a0f1a`

---

## 2. app-interface

Merge the **dataverse-terraform-lambda** MR first so `main` has that commit. If you already pushed the app-interface branch with ref `80fe814...`, it’s correct. If dataverse-terraform-lambda was merged with a different SHA (e.g. squash), update the ref in these two files to the new SHA, amend the commit, then push:

```bash
cd /home/daoneill/src/app-interface
# If you need to update ref after dataverse-terraform-lambda merge:
# edit data/aws/insights-stage/repos/tower-analytics-dataverse-lambda.yml
# edit data/aws/insights-prod/repos/tower-analytics-dataverse-lambda.yml
# git add ... && git commit --amend --no-gpg-sign --no-edit
git push -u origin chore/update-dataverse-lambda-ref
```

Then create the MR:

- **Source branch:** `chore/update-dataverse-lambda-ref`
- **Target:** `master` (or whatever app-interface uses)
- **Title:** `chore: point tower-analytics-dataverse-lambda at new ref`
- **Description:** Updates ref for tower-analytics-dataverse-lambda (stage + prod) so terraform-repo deploys batch 50 / 1000 and 900s timeout. Merge after [dataverse-terraform-lambda MR] is merged.

---

## Order

1. Push and merge **dataverse-terraform-lambda** `fix/batch-sizes-and-timeout`.
2. If the merged commit SHA differs from `80fe814...`, update the two app-interface YAML refs and amend the app-interface commit.
3. Push and merge **app-interface** `chore/update-dataverse-lambda-ref`.
