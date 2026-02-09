# Local Build Test

Build a container image locally using Podman and optionally run tests.

## Instructions

```text
skill_run("local_build_test", '{"repo": "$REPO", "tag": "", "dockerfile": "", "run_tests": "", "test_command": "", "cleanup": ""}')
```

## What It Does

Build a container image locally using Podman and optionally run tests.

Features:
- Build container image with Podman (not Docker)
- Tag with custom or auto-generated tag
- Run the container and execute tests
- Check health endpoints
- Verify database connectivity
- Clean up containers after testing

Uses: podman_build, podman_images, podman_run, podman_exec, podman_logs,
podman_stop, podman_rm, podman_pull, curl_get, curl_timing, psql_tables

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `repo` | Path to repository with Containerfile/Dockerfile | Yes |
| `tag` | Image tag (default: local-test) (default: local-test) | No |
| `dockerfile` | Containerfile/Dockerfile path relative to repo (default: Containerfile) | No |
| `run_tests` | Run tests inside the container after building (default: True) | No |
| `test_command` | Test command to run inside container (default: python -m pytest tests/ -x --tb=short) | No |
| `cleanup` | Remove container after testing (default: True) | No |
