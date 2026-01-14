---
name: deploy
description: "**Description:** Deploy a Merge Request to an ephemeral environment for testing."
arguments:
  - name: mr_id
---
# /deploy

**Description:** Deploy a Merge Request to an ephemeral environment for testing.

**Usage:**
```text
skill_run("test_mr_ephemeral", '{"mr_id": 1450}')
```

**Options:**
- `mr_id`: The GitLab MR number (required)
- `billing`: Deploy billing ClowdApp instead of main (default: false)
  ```text
  skill_run("test_mr_ephemeral", '{"mr_id": 1450, "billing": true}')
```
- `run_tests`: Run pytest after deployment (default: true)

**What it does:**

1. **Validates MR** - Checks MR exists and gets commit SHA
2. **Checks image** - Verifies Konflux build exists in Quay
3. **Reserves namespace** - Gets ephemeral namespace (4h default)
4. **Deploys** - Runs bonfire deploy with correct ClowdApp
5. **Waits for pods** - Monitors pod readiness
6. **Runs tests** - Executes smoke tests in the namespace
7. **Reports** - Shows deployment URL and test results

**ClowdApp auto-detection:**
The skill automatically determines whether to deploy the main or billing ClowdApp based on:
- Commit message content
- Jira issue summary
- Files changed (billing controller paths)

**Example:**
```bash
# Deploy MR 1450 to ephemeral
/deploy 1450

# Deploy billing changes
skill_run("test_mr_ephemeral", '{"mr_id": 1450, "billing": true}')
```

**Prerequisites:**
- Logged into ephemeral OpenShift cluster
- bonfire_venv activated
- Konflux build completed

**Cleanup:**
After testing, release the namespace:
```text
bonfire_namespace_release("ephemeral-xxxxx")
```

Or check your namespaces:
```text
/check-namespaces
```

**Note:** Test suite can take up to 90 minutes for full run. Smoke tests take ~5 minutes.
