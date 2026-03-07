#!/usr/bin/env bash
# Run this on your machine (VPN on) to push branches and create both MRs.
# Requires: git, glab (GitLab CLI) logged in to gitlab.cee.redhat.com

set -e

LAMBDA_REPO="/home/daoneill/src/dataverse-terraform-lambda"
APPINT_REPO="/home/daoneill/src/app-interface"

echo "==> Pushing dataverse-terraform-lambda..."
cd "$LAMBDA_REPO"
git push -u origin fix/batch-sizes-and-timeout

echo ""
echo "==> Creating MR: dataverse-terraform-lambda..."
glab mr create \
  --title "fix: batch 50 stage, 1000 prod; prod timeout 900s" \
  --description "Batch sizes and timeout for S3 sync Lambda.

- stage: batch_size 50
- prod: batch_size 1000, timeout 900s (15 min)

Merge this first, then merge the app-interface MR so terraform-repo picks up the new ref." \
  --target-branch main

echo ""
echo "==> Pushing app-interface..."
cd "$APPINT_REPO"
git push -u origin chore/update-dataverse-lambda-ref

echo ""
echo "==> Creating MR: app-interface..."
glab mr create \
  --title "chore: point tower-analytics-dataverse-lambda at new ref" \
  --description "Update ref for tower-analytics-dataverse-lambda (stage + prod).

Ref: 80fe814 (batch 50 stage, 1000 prod, 900s timeout).
Merge after the dataverse-terraform-lambda MR is merged so terraform-repo deploys the new config." \
  --target-branch master

echo ""
echo "Done. If app-interface uses a different default branch, edit the script and re-run the last glab mr create."
