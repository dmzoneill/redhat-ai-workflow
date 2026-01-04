# Development Guide

> How to contribute to the AI Workflow project

## Terminology

| Term | Meaning |
|------|---------|
| **Agent / Persona** | Tool configuration profile (developer, devops, incident, release). NOT a separate AI instance. |
| **Tool Module** | Directory (`tool_modules/aa-*/`) containing MCP tool implementations. |
| **Skill** | YAML workflow in `skills/` that chains tools. |

> This is a **single-agent system** with dynamic tool loading. "Agents" configure which tools Claude can use.

## Prerequisites

- Python 3.10+
- Git
- Access to GitLab/Jira/Kubernetes (for full functionality)
- Cursor IDE (for MCP integration)

## Setup

### 1. Clone and Install

```bash
git clone <repository-url> ~/src/redhat-ai-workflow
cd ~/src/redhat-ai-workflow

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode with all dependencies
pip install -e ".[dev]"
```

### 2. Configuration

Copy the example config and customize:

```bash
cp config.example.json config.json
# Edit config.json with your settings
```

Key configuration sections:
- `repositories` - Local repo paths and GitLab projects
- `jira` - Jira URL and project settings
- `kubernetes.environments` - Kubeconfig paths
- `slack` - Slack bot tokens and channels
- `user` - Your username and timezone

### 3. Environment Variables

Set these in your shell profile (`~/.bashrc` or `~/.zshrc`):

```bash
# Jira authentication
export JIRA_JPAT="your-jira-personal-access-token"
export JIRA_URL="https://issues.redhat.com"

# GitLab (for glab CLI)
export GITLAB_TOKEN="your-gitlab-token"

# Anthropic API (for Slack bot)
export ANTHROPIC_API_KEY="your-api-key"
# OR for Vertex AI:
export CLAUDE_CODE_USE_VERTEX=1
export ANTHROPIC_VERTEX_PROJECT_ID="your-gcp-project"
```

## Development Workflow

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=scripts/common --cov-report=term-missing

# Run specific test file
pytest tests/test_parsers.py -v

# Run specific test
pytest tests/test_parsers.py::test_extract_jira_key -v
```

### Linting

```bash
# Run all linters
flake8 tool_modules/ scripts/

# Format code
black tool_modules/ scripts/
isort tool_modules/ scripts/

# Type checking
mypy scripts/common/

# Security scan
bandit -r tool_modules/ scripts/ --severity high
```

### Pre-commit Hooks

```bash
# Install hooks
pre-commit install

# Run on all files
pre-commit run --all-files
```

## Project Structure

```
redhat-ai-workflow/
├── personas/                    # Agent persona definitions (YAML)
├── skills/                    # Workflow skill definitions (YAML)
├── memory/                    # Persistent memory storage
├── tool_modules/               # MCP tool modules
│   ├── server/             # Core server, shared utilities
│   ├── aa-workflow/           # Workflow tools (30+ tools)
│   ├── aa-git/                # Git operations
│   ├── aa-gitlab/             # GitLab integration
│   ├── aa-jira/               # Jira integration
│   ├── aa-k8s/                # Kubernetes operations
│   ├── aa-bonfire/            # Ephemeral environments
│   ├── aa-quay/               # Container registry
│   ├── aa-prometheus/         # Metrics queries
│   ├── aa-alertmanager/       # Alert management
│   ├── aa-kibana/             # Log search
│   ├── aa-google-calendar/    # Calendar integration
│   ├── aa-gmail/              # Email processing
│   ├── aa-slack/              # Slack integration
│   ├── aa-konflux/            # Build pipelines
│   └── aa-appinterface/       # App-interface config
├── scripts/                   # Python utilities
│   ├── common/                # Shared modules
│   │   ├── config_loader.py   # Configuration loading
│   │   ├── parsers.py         # Output parsers (42 functions)
│   │   └── jira_utils.py      # Jira utilities
│   ├── claude_agent.py        # Slack bot AI agent
│   └── slack_daemon.py        # Slack bot daemon
├── tests/                     # Test suite
├── docs/                      # Documentation
├── config/                    # Additional config modules
└── .cursor/commands/          # Cursor slash commands
```

## Adding New Tools

### 1. Choose the Right Module

- Add to existing module if it fits (e.g., new Git command → `aa-git`)
- Create new module for new service integrations

### 2. Create the Tool Function

In the appropriate `src/tools.py`:

```python
@server.tool()
async def my_new_tool(
    required_param: str,
    optional_param: str = "default",
) -> str:
    """
    Brief description of what this tool does.

    Args:
        required_param: What this parameter is for
        optional_param: What this optional parameter does

    Returns:
        Description of what's returned
    """
    # Implementation
    success, output = await run_cmd(["some", "command", required_param])

    if not success:
        return f"❌ Failed: {output}"

    return f"✅ Success: {output}"
```

### 3. Add Tests

In `tests/test_<module>.py`:

```python
def test_my_new_tool():
    """Test the new tool."""
    # Setup
    # ...

    # Execute
    result = await my_new_tool("test_param")

    # Assert
    assert "Success" in result
```

### 4. Update Documentation

Add entry to the relevant docs file in `docs/tool_modules/`.

## Adding New Skills

### 1. Create Skill YAML

In `skills/my_skill.yaml`:

```yaml
name: my_skill
description: What this skill does
version: "1.0"

inputs:
  - name: required_input
    type: string
    required: true
    description: What this input is for
  - name: optional_input
    type: string
    required: false
    default: "default_value"

steps:
  - id: step_1
    tool: some_tool
    args:
      param: "{{ required_input }}"

  - id: step_2
    tool: another_tool
    args:
      data: "{{ step_1.result }}"
    condition: "{{ step_1.success }}"

output:
  success: "{{ step_2.success }}"
  message: "Skill completed: {{ step_2.result }}"
```

### 2. Add Documentation

Create `docs/skills/my_skill.md`:

```markdown
# my_skill

> Brief description

## Usage

\`\`\`
skill_run("my_skill", {"required_input": "value"})
\`\`\`

## Inputs

| Name | Type | Required | Description |
|------|------|----------|-------------|
| required_input | string | Yes | What it's for |

## Steps

1. Does this first thing
2. Then does this

## Example

...
```

## Adding New Agents

### 1. Create Agent YAML

In `personas/my_agent.yaml`:

```yaml
name: my_agent
description: What this agent specializes in
version: "1.0"

modules:
  - workflow  # Always include
  - git
  - gitlab
  # Add other relevant modules

persona: |
  You are a specialized agent for [domain].

  Focus on:
  - First area of expertise
  - Second area

  Available tools: ...

skills:
  - skill_1
  - skill_2
```

### 2. Add Documentation

Create `docs/personas/my_agent.md`.

## Testing MCP Integration

### Quick Smoke Test

```bash
# Test that the server starts and tools load
python -c "
import sys
sys.path.insert(0, 'server')
from server.main import create_mcp_server
server = create_mcp_server(name='test', tools=['workflow'])
print('Server created successfully')
"
```

### Full Integration Test

```bash
pytest tests/test_mcp_integration.py -v
```

### Testing in Cursor

1. Update `.cursor/mcp.json` to point to your development server
2. Restart Cursor
3. Test tools via chat: "List available tools"

## Running the Slack Bot

### Development Mode

```bash
# Start the daemon
make slack-daemon-start

# Check status
make slack-daemon-status

# View logs
tail -f /tmp/slack-daemon.log

# Stop
make slack-daemon-stop
```

### Testing Locally

```bash
# Run the test script
python scripts/slack_test.py
```

## Debugging

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Common Issues

#### Import Errors

If you see `ModuleNotFoundError`:
1. Ensure you're in the virtual environment: `source .venv/bin/activate`
2. Reinstall: `pip install -e .`

#### Kubeconfig Issues

Never copy kubeconfig files. Always use the appropriate config:
- Stage: `~/.kube/config.s`
- Production: `~/.kube/config.p`
- Ephemeral: `~/.kube/config.e`

#### Pipenv Conflicts

When running tools that use `pipenv` (like `rh-issue`):
- The code automatically sets `PIPENV_IGNORE_VIRTUALENVS=1`
- If issues persist, ensure you're not in a nested virtualenv

## Code Style

### Python

- Follow PEP 8
- Use type hints for all public functions
- Max line length: 120 characters
- Use `Optional[T]` instead of `T | None` for compatibility

### Commit Messages

```
type: brief description

- Detail 1
- Detail 2
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### Documentation

- Use Markdown for all docs
- Include code examples
- Keep tables aligned

## Release Process

1. Update version in `pyproject.toml`
2. Update CHANGELOG
3. Run full test suite
4. Create MR with version bump
5. After merge, tag the release

## Getting Help

- Check existing documentation in `docs/`
- Review similar implementations in the codebase
- Ask in the team Slack channel
