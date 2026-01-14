# /run-local-tests

> Run the test suite locally using docker-compose.

## Overview

Run the test suite locally using docker-compose.

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
# Make sure docker-compose is running
cd ~/src/automation-analytics-backend
docker-compose up -d

# Run migrations
make migrations
make data

# Run tests
make test
```

```bash
# Get into the FastAPI container
docker exec -it automation-analytics-backend-api-fastapi-1 bash

# Inside container:
export POSTGRESQL_USER="debug"
export POSTGRESQL_PASSWORD="debug"
export SECRET_KEY="1234"
export DB_SSLMODE=disable
export DATABASE_PREFIX="postgresql://${POSTGRESQL_USER}:${POSTGRESQL_PASSWORD}@localhost"

# Run all tests
pytest -vv --tb=short

# Run specific test file
pytest test/test_hello.py -v

# Run tests matching a pattern
pytest -k "billing" -v
```

```bash
skill_run("review_pr", '{"mr_id": 1450, "run_tests": true}')
```

## Process Flow

This command invokes the `review_pr` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /run-local-tests]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call review_pr skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```

For detailed step-by-step process, see the [review_pr skill documentation](../skills/review_pr.md).

## Details

## Instructions

This command helps you run tests in the local development environment.

## Quick Start

```bash
# Make sure docker-compose is running
cd ~/src/automation-analytics-backend
docker-compose up -d

# Run migrations
make migrations
make data

# Run tests
make test
```

## Run Tests in Container

```bash
# Get into the FastAPI container
docker exec -it automation-analytics-backend-api-fastapi-1 bash

# Inside container:
export POSTGRESQL_USER="debug"
export POSTGRESQL_PASSWORD="debug"
export SECRET_KEY="1234"
export DB_SSLMODE=disable
export DATABASE_PREFIX="postgresql://${POSTGRESQL_USER}:${POSTGRESQL_PASSWORD}@localhost"

# Run all tests
pytest -vv --tb=short

# Run specific test file
pytest test/test_hello.py -v

# Run tests matching a pattern
pytest -k "billing" -v
```text

## Automated via Skill

For automated testing as part of PR review:

```
skill_run("review_pr", '{"mr_id": 1450, "run_tests": true}')
```


## Related Commands

_(To be determined based on command relationships)_
