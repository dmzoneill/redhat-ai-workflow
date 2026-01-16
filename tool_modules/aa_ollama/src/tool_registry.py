"""Tool registry for structured tool organization.

Provides a registry of all tools organized by category with methods for:
- Getting tools for categories
- Keyword matching
- Formatting for NPU prompts
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .categories import CORE_CATEGORIES, TOOL_CATEGORIES

logger = logging.getLogger(__name__)


@dataclass
class ToolCategory:
    """A category of related tools."""

    name: str
    description: str
    keywords: list[str]
    tools: list[str]
    priority: int = 5  # 1-10, higher = more likely to be selected


@dataclass
class ToolRegistry:
    """Registry of all tools organized by category."""

    categories: dict[str, ToolCategory] = field(default_factory=dict)

    def get_tools_for_categories(self, category_names: list[str]) -> list[str]:
        """Get all tools for given categories.

        Args:
            category_names: List of category names

        Returns:
            List of unique tool names
        """
        tools = set()
        for name in category_names:
            if name in self.categories:
                tools.update(self.categories[name].tools)
        return list(tools)

    def get_core_tools(self) -> list[str]:
        """Get tools from core categories (always included)."""
        return self.get_tools_for_categories(CORE_CATEGORIES)

    def keyword_match(self, text: str) -> list[str]:
        """Match text against category keywords.

        Args:
            text: Text to match

        Returns:
            List of matched category names
        """
        text_lower = text.lower()
        matched = []
        for name, cat in self.categories.items():
            for keyword in cat.keywords:
                if keyword.lower() in text_lower:
                    matched.append(name)
                    break
        return matched

    def get_categories_by_priority(self, min_priority: int = 5) -> list[str]:
        """Get categories with priority >= min_priority.

        Args:
            min_priority: Minimum priority threshold

        Returns:
            List of category names
        """
        return [name for name, cat in self.categories.items() if cat.priority >= min_priority]

    def to_prompt_format(self, exclude: set[str] | None = None) -> str:
        """Format categories for NPU prompt.

        Args:
            exclude: Categories to exclude from prompt

        Returns:
            Formatted string for NPU classification
        """
        exclude = exclude or set()
        lines = []
        for name, cat in sorted(self.categories.items(), key=lambda x: -x.priority):
            if name not in exclude:
                lines.append(f"- {name}: {cat.description}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Export registry as dict for JSON serialization."""
        return {
            name: {
                "description": cat.description,
                "keywords": cat.keywords,
                "tools": cat.tools,
                "priority": cat.priority,
            }
            for name, cat in self.categories.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolRegistry":
        """Create registry from dict."""
        registry = cls()
        for name, info in data.items():
            registry.categories[name] = ToolCategory(
                name=name,
                description=info.get("description", ""),
                keywords=info.get("keywords", []),
                tools=info.get("tools", []),
                priority=info.get("priority", 5),
            )
        return registry


# Cached registry instance
_registry: Optional[ToolRegistry] = None


def load_registry() -> ToolRegistry:
    """Load the tool registry.

    First tries to load from config.json, falls back to TOOL_CATEGORIES.

    Returns:
        Loaded ToolRegistry
    """
    global _registry
    if _registry is not None:
        return _registry

    # Try loading from config.json
    config_path = Path(__file__).parents[4] / "config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)

            custom_categories = config.get("tool_filtering", {}).get("categories")
            if custom_categories:
                logger.info("Loading tool categories from config.json")
                _registry = ToolRegistry.from_dict(custom_categories)
                return _registry
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load categories from config.json: {e}")

    # Fall back to built-in categories
    logger.info("Loading built-in tool categories")
    _registry = ToolRegistry.from_dict(TOOL_CATEGORIES)
    return _registry


def reload_registry() -> ToolRegistry:
    """Force reload the registry."""
    global _registry
    _registry = None
    return load_registry()


def get_tools_for_categories(category_names: list[str]) -> list[str]:
    """Convenience function to get tools for categories."""
    return load_registry().get_tools_for_categories(category_names)


def keyword_match(text: str) -> list[str]:
    """Convenience function for keyword matching."""
    return load_registry().keyword_match(text)
