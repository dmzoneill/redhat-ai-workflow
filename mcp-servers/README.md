# AA Modular MCP Servers

This directory contains modular MCP servers split by domain. Each server can be loaded independently based on your current task.

## Available Servers

| Server | Tools | Description |
|--------|-------|-------------|
| `aa-git` | 15 | Git repository operations (status, branch, commit, push, etc.) |
| `aa-jira` | 21 | Jira issue management (view, create, transition, comment) |
| `aa-gitlab` | 30 | GitLab MRs, CI/CD, issues (via API and glab CLI) |
| `aa-k8s` | 21 | Kubernetes operations (pods, deployments, logs, exec) |
| `aa-prometheus` | 13 | Prometheus queries, alerts, targets |
| `aa-alertmanager` | 5 | Alertmanager silences and status |
| `aa-kibana` | 9 | Log searching and analysis |
| `aa-konflux` | 13 | Konflux build pipelines and snapshots |
| `aa-bonfire` | 20 | Ephemeral namespace management |
| `aa-quay` | 8 | Container image verification |
| `aa-appinterface` | 6 | App-interface GitOps configuration |
| `aa-workflow` | 10 | High-level workflow orchestration, linting, testing |

**Total: 171 tools**

## Installation

Each server can be installed individually:

```bash
# From the mcp-servers directory
cd aa-git
pip install -e .
```

Or all at once:

```bash
for d in aa-*/; do pip install -e "$d"; done
```

## Usage in Cursor

Add servers to your `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "aa-git": {
      "command": "python",
      "args": ["-m", "aa_git.server"],
      "cwd": "/path/to/mcp-servers/aa-git"
    },
    "aa-jira": {
      "command": "python", 
      "args": ["-m", "aa_jira.server"],
      "cwd": "/path/to/mcp-servers/aa-jira"
    }
  }
}
```

## Example Configurations

See `/examples/` for common configurations:

- `mcp-full.json` - All servers loaded
- `mcp-minimal.json` - Just git + jira + gitlab
- `mcp-debugging.json` - k8s + prometheus + kibana
- `mcp-cicd.json` - konflux + bonfire + quay

## Environment Variables

Most servers use system authentication:

| Variable | Used By | Description |
|----------|---------|-------------|
| `JIRA_URL` | aa-jira | Jira instance URL |
| `JIRA_JPAT` | aa-jira | Jira Personal Access Token |
| `GITLAB_TOKEN` | aa-gitlab | GitLab API token |
| `KUBECONFIG` | aa-k8s | Default kubeconfig path |
| `KUBECONFIG_KONFLUX` | aa-konflux | Konflux cluster kubeconfig |
| `QUAY_TOKEN` | aa-quay | Quay.io API token (or uses Docker auth) |

## Server Architecture

Each server follows the same pattern:

```
aa-{name}/
├── pyproject.toml      # Package definition
├── src/
│   ├── __init__.py
│   └── server.py       # MCP server with @mcp.tool() decorators
```

The servers use `mcp.server.fastmcp.FastMCP` for the tool decorator pattern:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("aa-{name}")

@mcp.tool()
async def my_tool(arg: str) -> str:
    """Tool description."""
    return f"Result: {arg}"

def main():
    mcp.run(transport="stdio")
```

## Shared Library

`aa-common/` contains shared utilities:

- `config.py` - Configuration loading from config.json
- Common helper functions

## Adding a New Server

1. Create directory: `aa-{name}/`
2. Add `pyproject.toml` with dependencies
3. Create `src/__init__.py` and `src/server.py`
4. Register tools with `@mcp.tool()` decorator
5. Add `main()` entry point
