# Lint Tools

> aa_lint module for code quality, testing, and pre-commit hooks

## Diagram

```mermaid
classDiagram
    class LintBasic {
        +lint_python(repo, fix): str
        +lint_yaml(file): str
        +lint_dockerfile(file): str
        +test_run(repo, args): str
        +test_coverage(repo): str
        +security_scan(repo): str
        +precommit_run(repo, hook): str
    }
```

## Tool Categories

```mermaid
graph TB
    subgraph Linting[Code Linting]
        PYTHON[lint_python<br/>black, flake8, isort]
        YAML[lint_yaml<br/>yamllint]
        DOCKER[lint_dockerfile<br/>hadolint]
    end

    subgraph Testing[Test Execution]
        TEST[test_run<br/>pytest, npm test]
        COV[test_coverage<br/>coverage report]
    end

    subgraph Security[Security Scanning]
        SEC[security_scan<br/>bandit, safety]
    end

    subgraph Hooks[Pre-commit]
        PRECOMMIT[precommit_run<br/>Run hooks]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_lint/src/` | All lint and test tools |

## Tool Summary

| Tool | Description | Commands Used |
|------|-------------|---------------|
| `lint_python` | Run Python linters | black, flake8, isort |
| `lint_yaml` | Validate YAML files | yamllint |
| `lint_dockerfile` | Lint Dockerfiles | hadolint |
| `test_run` | Run project tests | pytest, npm test |
| `test_coverage` | Get coverage report | pytest --cov |
| `security_scan` | Security scanning | bandit, safety |
| `precommit_run` | Run pre-commit hooks | pre-commit run |

## Execution Flow

```mermaid
sequenceDiagram
    participant Tool as Lint Tool
    participant Resolve as Path Resolver
    participant Runner as Command Runner
    participant CLI as Linter CLI

    Tool->>Resolve: resolve_repo_path(repo)
    Resolve-->>Tool: Absolute path
    Tool->>Runner: run_cmd_full(command)
    Runner->>CLI: Execute linter
    CLI-->>Runner: Output + exit code
    Runner-->>Tool: success, stdout, stderr
    Tool->>Tool: Format output
    Tool-->>Tool: Return TextContent
```

## Configuration

Tools use project-level configuration from:

| File | Tool |
|------|------|
| `pyproject.toml` | black, isort, pytest |
| `.flake8` | flake8 |
| `.pre-commit-config.yaml` | pre-commit |
| `.yamllint` | yamllint |

## Usage Examples

```python
# Lint Python code (with auto-fix)
result = await lint_python("automation-analytics-backend", fix=True)

# Run tests
result = await test_run("automation-analytics-backend", args="-v -x")

# Run specific pre-commit hook
result = await precommit_run("myproject", hook="black")
```

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Git Tools](./git-tools.md)
- [Development Skills](../04-skills/common-skills.md)
