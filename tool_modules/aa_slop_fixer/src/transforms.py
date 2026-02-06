"""
AST-based Code Transforms for Slop Auto-Fix.

Provides safe, deterministic transforms for high-confidence fixes:
- unused_imports: Remove import statements
- unused_variables: Remove assignments or prefix with _
- bare_except: Change except: to except Exception:
- empty_except: Add logger.exception() call
- unreachable_code: Remove code after return/raise

Each transform:
1. Parses the file as AST
2. Locates the target line
3. Applies the minimal fix
4. Validates the result compiles
5. Returns the diff
"""

import ast
import difflib
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


async def apply_transform(
    file_path: str,
    line: int,
    category: str,
    suggestion: str = "",
    dry_run: bool = False,
) -> dict:
    """
    Apply a transform to fix an issue.

    Args:
        file_path: Path to the file
        line: Line number of the issue
        category: Category of the issue
        suggestion: Optional suggestion text for context
        dry_run: If True, don't modify the file

    Returns:
        Dict with success, action, diff, and error fields
    """
    try:
        # Read the file
        path = Path(file_path)
        if not path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        original_content = path.read_text()
        lines = original_content.splitlines(keepends=True)

        # Ensure line is valid
        if line < 1 or line > len(lines):
            return {"success": False, "error": f"Invalid line number: {line}"}

        # Apply the appropriate transform
        transform_func = TRANSFORMS.get(category)
        if not transform_func:
            return {"success": False, "error": f"No transform for category: {category}"}

        result = transform_func(lines, line, suggestion)

        if not result["success"]:
            return result

        new_content = "".join(result["lines"])

        # Validate the result compiles
        try:
            ast.parse(new_content)
        except SyntaxError as e:
            return {"success": False, "error": f"Transform produced invalid syntax: {e}"}

        # Generate diff
        diff = "".join(
            difflib.unified_diff(
                original_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                lineterm="",
            )
        )

        # Apply if not dry run
        if not dry_run:
            path.write_text(new_content)

        return {
            "success": True,
            "action": result["action"],
            "diff": diff,
            "lines_changed": result.get("lines_changed", 1),
        }

    except Exception as e:
        logger.exception(f"Transform error for {file_path}:{line}")
        return {"success": False, "error": str(e)}


def _transform_unused_imports(lines: list[str], line_num: int, suggestion: str) -> dict:
    """Remove an unused import line."""
    idx = line_num - 1  # Convert to 0-indexed

    if idx >= len(lines):
        return {"success": False, "error": "Line out of range"}

    target_line = lines[idx]

    # Check if it's an import line
    stripped = target_line.strip()
    if not (stripped.startswith("import ") or stripped.startswith("from ")):
        return {"success": False, "error": "Line is not an import statement"}

    # Remove the line
    new_lines = lines[:idx] + lines[idx + 1 :]

    return {
        "success": True,
        "lines": new_lines,
        "action": f"Removed unused import: {stripped[:50]}",
        "lines_changed": 1,
    }


def _transform_unused_variables(lines: list[str], line_num: int, suggestion: str) -> dict:
    """Handle unused variable - prefix with _ or remove if simple assignment."""
    idx = line_num - 1

    if idx >= len(lines):
        return {"success": False, "error": "Line out of range"}

    target_line = lines[idx]

    # Try to find the variable name from suggestion or line
    # Pattern: "variable 'foo'" or "foo = ..."
    var_match = re.search(r"['\"](\w+)['\"]", suggestion) or re.search(r"^(\s*)(\w+)\s*=", target_line)

    if not var_match:
        return {"success": False, "error": "Could not identify variable name"}

    if "'" in suggestion or '"' in suggestion:
        var_name = var_match.group(1)
        # Prefix with underscore
        new_line = re.sub(rf"\b{var_name}\b", f"_{var_name}", target_line, count=1)
        new_lines = lines[:idx] + [new_line] + lines[idx + 1 :]
        return {
            "success": True,
            "lines": new_lines,
            "action": f"Prefixed unused variable: {var_name} -> _{var_name}",
            "lines_changed": 1,
        }
    else:
        # Simple assignment pattern - remove the line if it's just an assignment
        var_name = var_match.group(2)

        # Check if it's a simple assignment we can remove
        # Don't remove if it has side effects (function calls, etc.)
        if "(" in target_line and "=" in target_line:
            # Has a function call - prefix instead of remove
            new_line = re.sub(rf"\b{var_name}\b", f"_{var_name}", target_line, count=1)
            new_lines = lines[:idx] + [new_line] + lines[idx + 1 :]
            return {
                "success": True,
                "lines": new_lines,
                "action": f"Prefixed unused variable: {var_name} -> _{var_name}",
                "lines_changed": 1,
            }
        else:
            # Simple assignment - can remove
            new_lines = lines[:idx] + lines[idx + 1 :]
            return {
                "success": True,
                "lines": new_lines,
                "action": f"Removed unused variable assignment: {var_name}",
                "lines_changed": 1,
            }


def _transform_bare_except(lines: list[str], line_num: int, suggestion: str) -> dict:
    """Change bare except: to except Exception:."""
    idx = line_num - 1

    if idx >= len(lines):
        return {"success": False, "error": "Line out of range"}

    target_line = lines[idx]

    # Match bare except
    if not re.search(r"^\s*except\s*:", target_line):
        return {"success": False, "error": "Line is not a bare except clause"}

    # Replace with except Exception:
    new_line = re.sub(r"except\s*:", "except Exception:", target_line)
    new_lines = lines[:idx] + [new_line] + lines[idx + 1 :]

    return {
        "success": True,
        "lines": new_lines,
        "action": "Changed bare except to except Exception:",
        "lines_changed": 1,
    }


def _transform_empty_except(lines: list[str], line_num: int, suggestion: str) -> dict:
    """Add logging to empty except block."""
    idx = line_num - 1

    if idx >= len(lines):
        return {"success": False, "error": "Line out of range"}

    target_line = lines[idx]

    # Check for except with pass on same line or next line
    if "pass" in target_line:
        # pass on same line as except - replace with logger
        indent_match = re.match(r"^(\s*)", target_line)
        indent = indent_match.group(1) if indent_match else ""

        # Check if it's "except: pass" or "except Exception: pass"
        if ":" in target_line and "pass" in target_line:
            # Split and add logging
            except_part = target_line.split("pass")[0].rstrip()
            new_line = except_part + "\n"
            log_line = indent + "    logger.exception('Caught exception')\n"
            new_lines = lines[:idx] + [new_line, log_line] + lines[idx + 1 :]
            return {
                "success": True,
                "lines": new_lines,
                "action": "Replaced pass with logger.exception()",
                "lines_changed": 2,
            }

    # Check if next line is just "pass"
    if idx + 1 < len(lines):
        next_line = lines[idx + 1]
        if next_line.strip() == "pass":
            indent_match = re.match(r"^(\s*)", next_line)
            indent = indent_match.group(1) if indent_match else "    "
            new_line = indent + "logger.exception('Caught exception')\n"
            new_lines = lines[: idx + 1] + [new_line] + lines[idx + 2 :]
            return {
                "success": True,
                "lines": new_lines,
                "action": "Replaced pass with logger.exception()",
                "lines_changed": 1,
            }

    return {"success": False, "error": "Could not identify empty except pattern"}


def _transform_unreachable_code(lines: list[str], line_num: int, suggestion: str) -> dict:
    """Remove unreachable code after return/raise/break/continue."""
    idx = line_num - 1

    if idx >= len(lines):
        return {"success": False, "error": "Line out of range"}

    target_line = lines[idx]

    # Remove this line (unreachable code after return/raise/break)
    new_lines = lines[:idx] + lines[idx + 1 :]

    return {
        "success": True,
        "lines": new_lines,
        "action": f"Removed unreachable code: {target_line.strip()[:40]}...",
        "lines_changed": 1,
    }


def _transform_dead_code(lines: list[str], line_num: int, suggestion: str) -> dict:
    """Remove dead code (unused function/class)."""
    idx = line_num - 1

    if idx >= len(lines):
        return {"success": False, "error": "Line out of range"}

    target_line = lines[idx]
    stripped = target_line.strip()

    # Check if it's a function or class definition
    if not (stripped.startswith("def ") or stripped.startswith("class ") or stripped.startswith("async def ")):
        # For other dead code, just remove the line
        new_lines = lines[:idx] + lines[idx + 1 :]
        return {
            "success": True,
            "lines": new_lines,
            "action": f"Removed dead code: {stripped[:40]}...",
            "lines_changed": 1,
        }

    # For function/class, need to remove the entire block
    base_indent = len(target_line) - len(target_line.lstrip())

    # Find the end of the block
    end_idx = idx + 1
    while end_idx < len(lines):
        line = lines[end_idx]
        if line.strip() == "":
            end_idx += 1
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= base_indent:
            break
        end_idx += 1

    # Remove the block
    new_lines = lines[:idx] + lines[end_idx:]

    return {
        "success": True,
        "lines": new_lines,
        "action": f"Removed dead {stripped.split()[0]}: {stripped[:40]}...",
        "lines_changed": end_idx - idx,
    }


# Map categories to transform functions
TRANSFORMS = {
    "unused_imports": _transform_unused_imports,
    "unused_variables": _transform_unused_variables,
    "bare_except": _transform_bare_except,
    "empty_except": _transform_empty_except,
    "unreachable_code": _transform_unreachable_code,
    "dead_code": _transform_dead_code,
}
