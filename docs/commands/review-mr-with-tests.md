# /review-mr-with-tests

> Full code review including checking out the branch and running the test suite locally.

## Overview

Full code review including checking out the branch and running the test suite locally.

**Underlying Skill:** `review_pr`

This command is a wrapper that calls the `review_pr` skill. For detailed process information, see [skills/review_pr.md](../skills/review_pr.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `mr_id` | No | - |
| `run_tests` | No | - |

## Usage

### Examples

```bash
skill_run("review_pr", '{"mr_id": $MR_ID, "run_tests": true}')
```

```bash
# Review with full test suite
skill_run("review_pr", '{"mr_id": 1450, "run_tests": true}')
```

## Process Flow

This command invokes the `review_pr` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /review-mr-with-tests]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call review_pr skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [review_pr skill documentation](../skills/review_pr.md).

## Details

## Instructions

Run a comprehensive review with local testing:

```
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


## Related Commands

_(To be determined based on command relationships)_
