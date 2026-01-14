# aa_lint - Code Quality Tools

Code linting, formatting, and testing tools.

## Overview

| Metric | Value |
|--------|-------|
| **Total Tools** | 7 |
| **Basic Tools** | 1 |
| **Extra Tools** | 6 |
| **Auto-Heal** | Yes |

## Tools

### Basic Tools (1)

| Tool | Description |
|------|-------------|
| `lint_python` | Run Python linters (black, flake8, isort) |

### Extra Tools (6)

| Tool | Description |
|------|-------------|
| `lint_yaml` | Validate YAML files |
| `lint_dockerfile` | Lint Dockerfiles with hadolint |
| `test_run` | Run tests (pytest/npm) |
| `test_coverage` | Get coverage report |
| `security_scan` | Run security scans (bandit/npm audit) |
| `precommit_run` | Run pre-commit hooks |

## Usage Examples

### Lint Python Code

```python
lint_python(repo="backend", fix=True)
```

This runs:
- **Black** - Code formatting
- **isort** - Import sorting
- **Flake8** - Style checking

### Run Tests

```python
test_run(repo="backend", marker="unit")
```

### Security Scan

```python
security_scan(repo="backend")
```

## Auto-Heal Support

All tools in this module are decorated with `@auto_heal()` for automatic recovery.

## Related Modules

- [dev_workflow](dev_workflow.md) - High-level workflow coordination
- [git](git.md) - Git operations (commit, push)
- [gitlab](gitlab.md) - CI/CD pipelines
