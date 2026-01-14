---
name: review-mr-with-tests
description: "Full code review including checking out the branch and running the test suite locally."
arguments:
  - name: mr_id
    required: true
  - name: run_tests
---
# Review MR with Local Tests

Full code review including checking out the branch and running the test suite locally.

## Instructions

Run a comprehensive review with local testing:

```text
skill_run("review_pr", '{"mr_id": $MR_ID, "run_tests": true}')
```

This will:
1. **Static Analysis** (same as /review-mr)
   - Fetch MR details, validate format, check pipelines

2. **Local Testing**
   - `git fetch origin && git checkout <branch>`
   - Check if docker-compose is running (start if not)
   - `make migrations && make data`
   - Run pytest in the FastAPI container

3. **Decision**
   - Tests pass + no issues → Auto-approve
   - Tests fail or issues found → Request changes with feedback

## Prerequisites

- Docker/Podman running
- docker-compose available
- Repository cloned locally

## Example

```bash
# Review with full test suite
skill_run("review_pr", '{"mr_id": 1450, "run_tests": true}')
```

⚠️ **Note:** This takes longer (~5-10 min) as it runs the full test suite.
