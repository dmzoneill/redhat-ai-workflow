"""Splitting source files into searchable chunks, and file/language selection."""

import re
from pathlib import Path
from typing import Any, NamedTuple

from tool_modules.aa_code_search.src.cs_config import CHUNK_OVERLAP, CHUNK_SIZE

_PY_DEFINITIONS = (
    ("class ", "class", re.compile(r"class\s+(\w+)")),
    ("def ", "function", re.compile(r"def\s+(\w+)")),
    ("async def ", "async_function", re.compile(r"async def\s+(\w+)")),
)

_EXT_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".sh": "shell",
    ".bash": "shell",
}

# Common non-code directories
_SKIP_DIRS = frozenset(
    {
        "__pycache__",
        "node_modules",
        "venv",
        ".venv",
        "env",
        "dist",
        "build",
        ".git",
        ".tox",
        "htmlcov",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
        "migrations",
        ".eggs",
    }
)

_CODE_EXTENSIONS = frozenset(
    {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".rb", ".yaml", ".yml", ".md", ".sh"}
)


class ChunkLabel(NamedTuple):
    """Where a chunk comes from and what it is."""

    file_path: str
    language: str
    type: str = "code"
    name: str = "unknown"


def _make_chunk(lines: list[str], label: ChunkLabel, start_line: int, end_line: int) -> dict[str, Any]:
    """Build the chunk dict stored in the index."""
    return {
        "content": "\n".join(lines),
        "file_path": label.file_path,
        "start_line": start_line,
        "end_line": end_line,
        "type": label.type,
        "name": label.name,
        "language": label.language,
    }


def _chunk_code_simple(content: str, file_path: str, language: str) -> list[dict]:
    """
    Simple code chunking by logical boundaries.

    For Python, chunks by:
    - Class definitions
    - Function definitions
    - Module-level code blocks
    """
    if language == "python":
        return _chunk_python_code(content, file_path)
    # Fallback: chunk by size with overlap
    return _chunk_by_size(content, ChunkLabel(file_path, language))


def _python_definition(line: str) -> tuple[str, str] | None:
    """(type, name) when ``line`` starts a top-level class or function, else None."""
    if line != line.lstrip():
        return None
    for prefix, def_type, pattern in _PY_DEFINITIONS:
        if line.startswith(prefix):
            match = pattern.match(line)
            return def_type, match.group(1) if match else "unknown"
    return None


def _split_python_definitions(content: str, file_path: str) -> list[dict[str, Any]]:
    """One chunk per top-level definition (plus the module-level code before the first)."""
    chunks: list[dict[str, Any]] = []
    lines = content.split("\n")
    label = ChunkLabel(file_path, "python", "module", "module")
    current: list[str] = []
    start = 1

    for i, line in enumerate(lines, 1):
        definition = _python_definition(line)
        if definition and current:
            if "\n".join(current).strip():
                chunks.append(_make_chunk(current, label, start, i - 1))
            current = []
            start = i
            label = label._replace(type=definition[0], name=definition[1])
        current.append(line)

    if current and "\n".join(current).strip():
        chunks.append(_make_chunk(current, label, start, len(lines)))
    return chunks


def _chunk_python_code(content: str, file_path: str) -> list[dict]:
    """Chunk Python code by functions and classes, splitting oversized definitions by size."""
    final_chunks: list[dict[str, Any]] = []
    for chunk in _split_python_definitions(content, file_path):
        if len(chunk["content"]) > CHUNK_SIZE * 2:
            label = ChunkLabel(chunk["file_path"], "python", chunk["type"], chunk["name"])
            final_chunks.extend(_chunk_by_size(chunk["content"], label, base_line=chunk["start_line"]))
        else:
            final_chunks.append(chunk)
    return final_chunks


def _chunk_by_size(content: str, label: ChunkLabel, base_line: int = 1) -> list[dict]:
    """Chunk content by size with overlap."""
    chunks: list[dict[str, Any]] = []
    overlap_lines = int(CHUNK_OVERLAP / 50)  # Approximate lines for overlap

    current: list[str] = []
    current_start = base_line
    current_size = 0

    for line in content.split("\n"):
        line_size = len(line) + 1  # +1 for newline

        if current_size + line_size > CHUNK_SIZE and current:
            chunks.append(_make_chunk(current, label, current_start, current_start + len(current) - 1))

            # Start new chunk with overlap
            current = current[-overlap_lines:] if overlap_lines > 0 else []
            current_start = current_start + len(current) - overlap_lines
            current_size = sum(len(line_text) + 1 for line_text in current)

        current.append(line)
        current_size += line_size

    if current:
        chunks.append(_make_chunk(current, label, current_start, current_start + len(current) - 1))
    return chunks


def _get_language(file_path: str) -> str:
    """Detect language from file extension."""
    return _EXT_LANGUAGES.get(Path(file_path).suffix.lower(), "unknown")


def _should_index_file(file_path: Path, project_path: Path) -> bool:
    """Check if file should be indexed."""
    rel_parts = file_path.relative_to(project_path).parts
    # Skip hidden files and directories
    if any(part.startswith(".") for part in rel_parts):
        return False
    if any(part in _SKIP_DIRS for part in rel_parts):
        return False
    # Only index code files
    return file_path.suffix.lower() in _CODE_EXTENSIONS
