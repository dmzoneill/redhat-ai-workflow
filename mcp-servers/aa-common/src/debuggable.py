"""Auto-debug infrastructure for MCP tools.

Provides:
- @debuggable decorator to capture source info and add debug hints on failure
- Tool registry mapping tool names to source files
- debug_tool() function for Claude to inspect and fix broken tools

Usage:
    from .debuggable import debuggable, register_debug_tool

    @server.tool()
    @debuggable
    async def my_tool(...):
        ...

When a tool fails, it will include a hint:
    💡 To auto-fix: `debug_tool('my_tool')`

Claude can then call debug_tool() to inspect the source and propose a fix.
"""

import functools
import inspect
import logging
import re
from pathlib import Path
from typing import Any, Callable

from mcp.types import TextContent

logger = logging.getLogger(__name__)


# Global registry of tools and their source locations
TOOL_REGISTRY: dict[str, dict[str, Any]] = {}


def debuggable(func: Callable) -> Callable:
    """
    Decorator that enables auto-debugging for MCP tools.
    
    Captures source file and line info at decoration time.
    On failure (result starts with ❌ or exception), adds a debug hint.
    """
    # Capture source location
    try:
        source_file = inspect.getfile(func)
        source_lines, start_line = inspect.getsourcelines(func)
        end_line = start_line + len(source_lines) - 1
    except (TypeError, OSError):
        source_file = "unknown"
        start_line = 0
        end_line = 0
        source_lines = []
    
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            result = await func(*args, **kwargs)
            
            # Check if result indicates failure
            if isinstance(result, list) and result:
                first = result[0]
                text = first.text if hasattr(first, 'text') else str(first)
                
                if text.startswith("❌"):
                    # Extract first line of error for context
                    error_first_line = text.split('\n')[0][:100]
                    
                    # Add debug hint
                    debug_hint = TextContent(
                        type="text",
                        text=f"\n---\n💡 **Auto-fix available:** `debug_tool('{func.__name__}')`"
                    )
                    result.append(debug_hint)
                    
                    # Log for debugging
                    logger.warning(f"Tool {func.__name__} failed: {error_first_line}")
            
            return result
            
        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Tool {func.__name__} crashed")
            
            return [TextContent(type="text", text=f"""❌ **{func.__name__}** crashed

**Error:** `{error_msg}`

**Source:** `{source_file}:{start_line}`

---
💡 **Auto-fix available:** `debug_tool('{func.__name__}', '{error_msg[:80]}')`
""")]
    
    # Store source info on the wrapper for later retrieval
    wrapper._debug_info = {
        "source_file": source_file,
        "start_line": start_line,
        "end_line": end_line,
        "func_name": func.__name__,
    }
    
    # Register in global registry
    TOOL_REGISTRY[func.__name__] = wrapper._debug_info
    
    return wrapper


def get_tool_source(tool_name: str) -> tuple[str, str, int, int]:
    """
    Get source code for a tool.
    
    Returns:
        (source_file, function_source, start_line, end_line)
    """
    info = TOOL_REGISTRY.get(tool_name)
    
    if not info:
        # Try to find by searching MCP server directories
        info = _search_for_tool(tool_name)
    
    if not info:
        return "", f"# Tool '{tool_name}' not found in registry", 0, 0
    
    source_file = info["source_file"]
    
    try:
        with open(source_file) as f:
            full_source = f.read()
        
        # Extract just this function
        func_source = _extract_function(full_source, tool_name)
        
        return source_file, func_source, info["start_line"], info["end_line"]
    except Exception as e:
        return source_file, f"# Error reading source: {e}", 0, 0


def _search_for_tool(tool_name: str) -> dict | None:
    """Search MCP server directories for a tool definition."""
    # Get the mcp-servers directory
    this_file = Path(__file__)
    servers_dir = this_file.parent.parent.parent  # aa-common/src -> aa-common -> mcp-servers
    
    if not servers_dir.exists():
        return None
    
    # Search all tools.py files
    for tools_file in servers_dir.glob("*/src/tools.py"):
        try:
            with open(tools_file) as f:
                content = f.read()
            
            # Look for function definition
            pattern = rf"async def {tool_name}\s*\("
            match = re.search(pattern, content)
            
            if match:
                # Found it - calculate line number
                line_num = content[:match.start()].count('\n') + 1
                
                # Extract function to count lines
                func_source = _extract_function(content, tool_name)
                end_line = line_num + func_source.count('\n')
                
                return {
                    "source_file": str(tools_file),
                    "start_line": line_num,
                    "end_line": end_line,
                    "func_name": tool_name,
                }
        except Exception:
            continue
    
    return None


def _extract_function(source: str, func_name: str) -> str:
    """Extract a function's source code from a file."""
    lines = source.split('\n')
    
    # Find function start
    start_idx = None
    for i, line in enumerate(lines):
        if re.match(rf'\s*async def {func_name}\s*\(', line) or \
           re.match(rf'\s*def {func_name}\s*\(', line):
            start_idx = i
            break
    
    if start_idx is None:
        return f"# Function {func_name} not found"
    
    # Find function end (next function at same or lower indentation)
    func_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
    end_idx = len(lines)
    
    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        
        current_indent = len(line) - len(line.lstrip())
        
        # Check for decorator or def at same/lower indentation level
        if current_indent <= func_indent:
            if line.strip().startswith('@') or \
               line.strip().startswith('def ') or \
               line.strip().startswith('async def ') or \
               line.strip().startswith('class ') or \
               line.strip().startswith('return ') and current_indent == func_indent:
                # Check if it's a return statement inside the function
                if not (line.strip().startswith('return ') and current_indent > func_indent):
                    end_idx = i
                    break
    
    return '\n'.join(lines[start_idx:end_idx])


def register_debug_tool(server) -> None:
    """Register the debug_tool with an MCP server."""
    
    @server.tool()
    async def debug_tool(
        tool_name: str,
        error_message: str = "",
    ) -> list[TextContent]:
        """
        Analyze a failed MCP tool and help Claude diagnose/fix it.
        
        When a tool fails, call this to inspect its source code.
        Claude will analyze the code against the error and propose a fix.
        User confirms before any changes are applied.
        
        Args:
            tool_name: Name of the tool that failed (e.g., 'bonfire_namespace_release')
            error_message: The error message from the failure (optional but helpful)
        
        Returns:
            Source code and instructions for Claude to diagnose and fix.
        """
        source_file, func_source, start_line, end_line = get_tool_source(tool_name)
        
        if not source_file:
            return [TextContent(type="text", text=f"""❌ Could not find tool `{tool_name}`

**Available tools in registry:**
{chr(10).join(f'- {name}' for name in sorted(TOOL_REGISTRY.keys())[:20])}

If the tool exists but isn't registered, it may not have the @debuggable decorator.
""")]
        
        # Build the debug prompt
        lines = [
            f"## 🔧 Debug: `{tool_name}`",
            "",
        ]
        
        if error_message:
            lines.extend([
                "**Error:**",
                "```",
                error_message[:500],
                "```",
                "",
            ])
        
        lines.extend([
            f"**Source file:** `{source_file}`",
            f"**Lines:** {start_line}-{end_line}",
            "",
            "**Function code:**",
            "```python",
            func_source,
            "```",
            "",
            "---",
            "",
            "## Instructions for Claude",
            "",
            "1. **Analyze** the error message against the source code",
            "2. **Identify** the bug (wrong flag, missing parameter, logic error, etc.)",
            "3. **Propose a fix** using the `search_replace` tool with:",
            f"   - `file_path`: `{source_file}`",
            "   - `old_string`: The exact code to replace",
            "   - `new_string`: The fixed code",
            "4. **Ask user to confirm** before applying",
            "5. After fix is applied, **commit** with message: `fix({tool_name}): <description>`",
            "",
            "Common issues to check:",
            "- Missing CLI flags (--force, --yes, etc. for non-interactive)",
            "- Wrong flag syntax (--state vs --closed/--merged)",
            "- Missing environment variables",
            "- Incorrect string formatting",
            "- Wrong API endpoints or parameters",
        ])
        
        return [TextContent(type="text", text="\n".join(lines))]


def wrap_all_tools(server, tools_module) -> int:
    """
    Retroactively register all tools from a module in the debug registry.
    
    Call this after all tools are registered to enable debugging for tools
    that weren't decorated with @debuggable.
    
    Returns:
        Number of tools registered.
    """
    import inspect as insp
    
    count = 0
    source_file = insp.getfile(tools_module)
    
    # Read the full source
    try:
        with open(source_file) as f:
            full_source = f.read()
    except Exception:
        return 0
    
    # Find all async def functions that look like tools
    for match in re.finditer(r'async def (\w+)\s*\(', full_source):
        func_name = match.group(1)
        
        if func_name.startswith('_'):
            continue
        
        if func_name in TOOL_REGISTRY:
            continue
        
        # Calculate line number
        line_num = full_source[:match.start()].count('\n') + 1
        
        # Extract function
        func_source = _extract_function(full_source, func_name)
        end_line = line_num + func_source.count('\n')
        
        TOOL_REGISTRY[func_name] = {
            "source_file": source_file,
            "start_line": line_num,
            "end_line": end_line,
            "func_name": func_name,
        }
        count += 1
    
    return count

