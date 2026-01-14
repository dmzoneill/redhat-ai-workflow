---
name: run-local-tests
description: "Run the test suite locally using docker-compose."
arguments:
  - name: mr_id
  - name: run_tests
---
# Run Local Tests

Run the test suite locally using docker-compose.

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
