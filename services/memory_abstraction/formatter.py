"""
Result Formatter - Format QueryResult as LLM-friendly markdown.

This module formats memory query results into markdown that's
optimized for LLM context injection:

1. Intent classification at the top (helps LLM understand context)
2. Results grouped by source
3. Relevance scores for weighting
4. Code blocks preserved
5. Intelligent truncation

Usage:
    from services.memory_abstraction.formatter import ResultFormatter

    formatter = ResultFormatter()
    markdown = formatter.format(query_result)
"""

import logging
from typing import Any

from .models import MemoryItem, QueryResult

logger = logging.getLogger(__name__)


class ResultFormatter:
    """
    Format QueryResult as LLM-friendly markdown.

    Output is grouped by source with intent classification at the top.
    """

    def __init__(
        self,
        max_tokens: int = 4000,
        max_content_length: int = 500,
        include_metadata: bool = True,
    ):
        """
        Initialize the formatter.

        Args:
            max_tokens: Approximate max tokens for output (rough estimate)
            max_content_length: Max characters per item content
            include_metadata: Whether to include item metadata
        """
        self.max_tokens = max_tokens
        self.max_content_length = max_content_length
        self.include_metadata = include_metadata

        # Rough estimate: 4 chars per token
        self.max_chars = max_tokens * 4

    def format(self, result: QueryResult) -> str:
        """
        Format QueryResult as markdown.

        Args:
            result: QueryResult to format

        Returns:
            Markdown string ready for LLM context injection
        """
        sections = []

        # Intent classification section (always first)
        sections.append(self._format_intent(result))

        if not result.has_results():
            sections.append("\n*No results found.*")
            if result.errors:
                sections.append(self._format_errors(result.errors))
            return "\n".join(sections)

        # Group items by source
        by_source = self._group_by_source(result.items)

        # Format each source group
        for source, items in by_source.items():
            section = self._format_source_group(source, items)
            sections.append(section)

        # Add errors if any
        if result.errors:
            sections.append(self._format_errors(result.errors))

        # Join and truncate if needed
        output = "\n\n".join(sections)

        if len(output) > self.max_chars:
            output = self._truncate(output)

        return output

    def _format_intent(self, result: QueryResult) -> str:
        """Format the intent classification section."""
        intent = result.intent
        confidence_pct = int(intent.confidence * 100)

        lines = [
            "## Query Analysis",
            f"- **Intent**: {intent.intent} (confidence: {confidence_pct}%)",
            f"- **Sources**: {', '.join(result.sources_queried)}",
        ]

        return "\n".join(lines)

    def _group_by_source(self, items: list[MemoryItem]) -> dict[str, list[MemoryItem]]:
        """Group items by source, maintaining order."""
        groups: dict[str, list[MemoryItem]] = {}

        for item in items:
            if item.source not in groups:
                groups[item.source] = []
            groups[item.source].append(item)

        return groups

    def _format_source_group(
        self,
        source: str,
        items: list[MemoryItem],
    ) -> str:
        """Format a group of items from the same source."""
        # Get display name for source
        display_name = self._get_source_display_name(source)

        # Calculate average relevance
        avg_relevance = sum(i.relevance for i in items) / len(items) if items else 0
        relevance_pct = int(avg_relevance * 100)

        lines = [f"### From {display_name} (relevance: {relevance_pct}%)"]

        for item in items:
            formatted = self._format_item(item)
            lines.append(formatted)

        return "\n\n".join(lines)

    def _format_item(self, item: MemoryItem) -> str:
        """Format a single MemoryItem."""
        lines = []

        # Summary line with metadata
        summary_line = f"**{item.summary}**"
        if self.include_metadata and item.metadata:
            meta_str = self._format_metadata(item)
            if meta_str:
                summary_line += f" - {meta_str}"

        lines.append(summary_line)

        # Content (with appropriate formatting)
        content = self._format_content(item)
        if content:
            lines.append(content)

        return "\n".join(lines)

    def _format_content(self, item: MemoryItem) -> str:
        """Format item content based on type."""
        content = item.content

        if not content:
            return ""

        # Truncate if needed
        if len(content) > self.max_content_length:
            content = content[: self.max_content_length] + "..."

        # Format based on type
        if item.type == "code_snippet":
            # Detect language from metadata
            lang = item.metadata.get("language", "")
            if not lang:
                # Try to infer from file path
                file_path = item.metadata.get("file_path", "")
                lang = self._infer_language(file_path)

            return f"```{lang}\n{content}\n```"

        elif item.type == "message":
            # Quote format for messages
            return f"> {content}"

        elif item.type == "document":
            # Quote format for documents
            return f"> {content}"

        else:
            # Default: plain text
            return content

    def _format_metadata(self, item: MemoryItem) -> str:
        """Format item metadata as inline string."""
        meta = item.metadata
        parts = []

        # File path for code
        if "file_path" in meta:
            path = meta["file_path"]
            if "start_line" in meta and "end_line" in meta:
                path += f":{meta['start_line']}-{meta['end_line']}"
            parts.append(f"`{path}`")

        # User for messages
        if "user" in meta:
            parts.append(f"@{meta['user']}")

        # Timestamp
        if "datetime" in meta:
            parts.append(meta["datetime"])

        # Status for issues
        if "status" in meta:
            parts.append(f"Status: {meta['status']}")

        return ", ".join(parts)

    def _format_errors(self, errors: dict[str, str]) -> str:
        """Format error messages."""
        lines = ["### Errors"]
        for source, error in errors.items():
            lines.append(f"- **{source}**: {error}")
        return "\n".join(lines)

    def _get_source_display_name(self, source: str) -> str:
        """Get display name for a source."""
        display_names = {
            "code": "Code Search",
            "slack": "Slack Conversations",
            "yaml": "Memory State",
            "inscope": "InScope AI",
            "jira": "Jira Issues",
        }
        return display_names.get(source, source.title())

    def _infer_language(self, file_path: str) -> str:
        """Infer programming language from file path."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".rb": "ruby",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".md": "markdown",
            ".sh": "bash",
            ".sql": "sql",
        }

        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang

        return ""

    def _truncate(self, output: str) -> str:
        """Truncate output to max length, preserving structure."""
        if len(output) <= self.max_chars:
            return output

        # Try to truncate at a section boundary
        truncated = output[: self.max_chars]

        # Find last complete section (###)
        last_section = truncated.rfind("\n### ")
        if last_section > self.max_chars // 2:
            truncated = truncated[:last_section]

        return truncated + "\n\n*[Results truncated]*"

    def format_compact(self, result: QueryResult) -> str:
        """
        Format result in a more compact form.

        Useful for smaller context windows.
        """
        lines = []

        # One-line intent
        intent = result.intent
        lines.append(f"**Intent**: {intent.intent} ({int(intent.confidence*100)}%)")

        # Compact item list
        for item in result.items[:10]:  # Max 10 items
            relevance = int(item.relevance * 100)
            lines.append(f"- [{item.source}] {item.summary} ({relevance}%)")

        if result.total_count > 10:
            lines.append(f"*...and {result.total_count - 10} more results*")

        return "\n".join(lines)
