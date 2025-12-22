# Modular MCP Server Architecture

## Design Principles

1. **Shared Infrastructure**: Server setup (stdio, web, logging) is in `aa-common`
2. **Tool Modules**: Each domain has tools in a `tools.py` with `register_tools(server)` function
3. **Dual Mode**: Each module can run standalone OR be loaded as a plugin

## Directory Structure

```
mcp-servers/
├── aa-common/                    # Shared infrastructure
│   ├── src/
│   │   ├── __init__.py
│   │   ├── server.py             # Main server with tool loading
│   │   ├── config.py             # Shared configuration
│   │   └── web.py                # Web UI (optional)
│   └── pyproject.toml
│
├── aa-git/                       # Example tool module
│   ├── src/
│   │   ├── __init__.py           # Exports register_tools
│   │   ├── tools.py              # Tool definitions with register_tools(server)
│   │   └── server.py             # Thin standalone wrapper
│   └── pyproject.toml
│
└── aa-{other}/                   # Same pattern for all modules
```

## Tool Module Pattern

### tools.py - The Tool Definitions

```python
"""Git tool definitions."""

from mcp.server.fastmcp import FastMCP

def register_tools(server: FastMCP) -> int:
    """Register tools with the server.
    
    Args:
        server: FastMCP server instance
    
    Returns:
        Number of tools registered
    """
    
    @server.tool()
    async def git_status(repo: str) -> str:
        """Get git status."""
        # Implementation
        return "..."
    
    @server.tool()
    async def git_log(repo: str, limit: int = 10) -> str:
        """Get git log."""
        # Implementation  
        return "..."
    
    return 2  # Number of tools
```

### server.py - Standalone Wrapper

```python
"""Standalone entry point for aa-git."""

import asyncio
from mcp.server.fastmcp import FastMCP
from .tools import register_tools

def main():
    server = FastMCP("aa-git")
    register_tools(server)
    asyncio.run(server.run_stdio_async())

if __name__ == "__main__":
    main()
```

### __init__.py - Export

```python
from .tools import register_tools
__all__ = ["register_tools"]
```

## Usage Patterns

### 1. Single Tool Module (Standalone)

Run just git tools:

```bash
python -m aa_git.server
```

Cursor config:
```json
{
  "mcpServers": {
    "aa-git": {
      "command": "python",
      "args": ["-m", "aa_git.server"]
    }
  }
}
```

### 2. Multiple Tool Modules (Combined)

Run git + jira + gitlab:

```bash
python -m aa_common.server --tools git,jira,gitlab
```

Cursor config:
```json
{
  "mcpServers": {
    "aa-workflow": {
      "command": "python",
      "args": ["-m", "aa_common.server", "--tools", "git,jira,gitlab"]
    }
  }
}
```

### 3. All Tools

```bash
python -m aa_common.server --all
```

### 4. With Web UI

```bash
python -m aa_common.server --tools git,jira --web --port 8765
```

## Adding a New Tool Module

1. Create directory: `aa-{name}/src/`

2. Create `tools.py`:
```python
from mcp.server.fastmcp import FastMCP

def register_tools(server: FastMCP) -> int:
    @server.tool()
    async def my_tool(arg: str) -> str:
        """Tool description."""
        return f"Result: {arg}"
    
    return 1
```

3. Create `__init__.py`:
```python
from .tools import register_tools
__all__ = ["register_tools"]
```

4. Create `server.py`:
```python
import asyncio
from mcp.server.fastmcp import FastMCP
from .tools import register_tools

def main():
    server = FastMCP("aa-{name}")
    register_tools(server)
    asyncio.run(server.run_stdio_async())

if __name__ == "__main__":
    main()
```

5. Add to `aa-common/src/server.py` TOOL_MODULES:
```python
TOOL_MODULES = {
    # ...
    "{name}": "aa_{name}.tools",
}
```

## Benefits

1. **No Code Duplication**: Server infrastructure is shared
2. **Flexible Loading**: Load any combination of tools
3. **Easy Testing**: Test individual tools or combinations
4. **Cursor Compatible**: Works with Cursor's MCP config
5. **Maintainable**: Each domain is isolated

