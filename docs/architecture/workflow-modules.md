# AA-Workflow Module Architecture

> Internal module structure for developers working on the aa-workflow MCP server

## Overview

The aa-workflow server provides workflow automation tools. The codebase has been organized into focused modules for maintainability.

## Module Reference

### Core Modules

| Module | Purpose | Tools |
|--------|---------|-------|
| `tools.py` | Main entry point, imports all modules | Registers 30+ tools |
| `constants.py` | Shared path constants | MEMORY_DIR, AGENTS_DIR, SKILLS_DIR |

### Tool Modules

| Module | Purpose | Tools Provided |
|--------|---------|----------------|
| `workflow_tools.py` | High-level workflow coordination | 9 tools |
| `memory_tools.py` | Persistent context storage | 5 tools |
| `agent_tools.py` | AI persona management | 2 tools |
| `session_tools.py` | Session bootstrap + prompts | 1 tool + 3 prompts |
| `skill_engine.py` | Multi-step workflow execution | 2 tools + SkillExecutor class |
| `infra_tools.py` | VPN and Kubernetes auth | 2 tools |
| `lint_tools.py` | Code quality and testing | 7 tools |
| `meta_tools.py` | Dynamic tool discovery | 2 tools |

### Resource Modules

| Module | Purpose | Resources Provided |
|--------|---------|-------------------|
| `resources.py` | MCP resource handlers | 5 resources |

## Tool Details

### workflow_tools.py (9 tools)

| Tool | Description |
|------|-------------|
| `workflow_start_work` | Get context to start working on a Jira issue |
| `workflow_check_deploy_readiness` | Check if MR is ready to deploy |
| `workflow_review_feedback` | Get guidance on addressing review feedback |
| `workflow_create_branch` | Create a feature branch from a Jira issue |
| `workflow_prepare_mr` | Prepare a Merge Request (push + glab command) |
| `workflow_run_local_checks` | Run local linting and validation |
| `workflow_monitor_pipelines` | Monitor GitLab + Konflux pipelines |
| `workflow_handle_review` | Prepare to handle MR review feedback |
| `workflow_daily_standup` | Generate standup summary from git history |

### memory_tools.py (5 tools)

| Tool | Description |
|------|-------------|
| `memory_read` | Read from persistent memory files |
| `memory_write` | Write complete memory files |
| `memory_update` | Update specific fields in memory |
| `memory_append` | Append items to lists in memory |
| `memory_session_log` | Log actions to session log |

### agent_tools.py (2 tools)

| Tool | Description |
|------|-------------|
| `agent_list` | List available agent personas |
| `agent_load` | Load an agent with its tools and persona |

### session_tools.py (1 tool + 3 prompts)

| Tool/Prompt | Description |
|-------------|-------------|
| `session_start` | Initialize a new work session with context |
| `session_init` (prompt) | Guided session initialization |
| `debug_guide` (prompt) | Debug workflow guide |
| `review_guide` (prompt) | Review workflow guide |

### skill_engine.py (2 tools)

| Tool | Description |
|------|-------------|
| `skill_list` | List available skills |
| `skill_run` | Execute a skill |

The `SkillExecutor` class handles multi-step workflow execution with:
- Variable substitution
- Conditional steps
- Error handling
- Result accumulation

### infra_tools.py (2 tools)

| Tool | Description |
|------|-------------|
| `vpn_connect` | Connect to the Red Hat VPN |
| `kube_login` | Refresh Kubernetes credentials |

### lint_tools.py (7 tools)

| Tool | Description |
|------|-------------|
| `lint_python` | Run Python linters (black, flake8, isort) |
| `lint_yaml` | Validate YAML files with yamllint |
| `lint_dockerfile` | Lint Dockerfiles with hadolint |
| `test_run` | Run tests (pytest or npm test) |
| `test_coverage` | Get coverage report |
| `security_scan` | Run security scanning (bandit/npm audit) |
| `precommit_run` | Run pre-commit hooks |

### meta_tools.py (2 tools)

| Tool | Description |
|------|-------------|
| `tool_list` | List all available tools across all modules |
| `tool_exec` | Execute any tool dynamically |

### resources.py (5 resources)

| Resource | URI | Description |
|----------|-----|-------------|
| Current Work | `memory://current_work` | Active issues, branches, MRs |
| Patterns | `memory://patterns` | Learned error patterns |
| Agents | `config://agents` | Available agent definitions |
| Skills | `config://skills` | Available skill definitions |
| Repositories | `config://repositories` | Configured repositories |

## Import Structure

All modules support both:
1. **Package import**: `from .constants import MEMORY_DIR`
2. **Direct loading**: Falls back to Path-based resolution

This allows the MCP server to load modules dynamically via `importlib`.

## Adding New Tools

1. Create a new module `my_tools.py` in `src/`
2. Define a `register_my_tools(server: FastMCP) -> int` function
3. Register tools using `@server.tool()` decorator
4. Add import in `tools.py` register_tools function
5. Add test in `tests/test_mcp_integration.py`

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run integration tests only
pytest tests/test_mcp_integration.py -v

# Test module loading
python -c "
import sys
sys.path.insert(0, 'mcp-servers/aa-common')
from src.server import create_mcp_server
server = create_mcp_server(name='aa-workflow', tools=['workflow'])
print('Server created with 30+ tools')
"
```

## Related

- [Workflow Tools](../mcp-servers/workflow.md) - User-facing documentation
- [MCP Implementation](mcp-implementation.md) - Overall MCP architecture
