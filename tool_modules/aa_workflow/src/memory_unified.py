"""Unified Memory Tools - Single interface for all memory operations.

These tools provide a simplified interface to the memory abstraction layer,
reducing the cognitive load on LLMs by providing a single entry point
for querying multiple data sources.

Tools:
- memory_ask: Query memory with auto-routing to appropriate sources
- memory_search: Semantic search across sources
- memory_store: Store data in memory
- memory_health: Check health of all memory adapters
- memory_list_adapters: List available adapters and their capabilities
"""

import json
import logging
from typing import TYPE_CHECKING

from fastmcp import Context

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _get_memory_interface(ctx: Context | None = None):
    """Get the memory interface from context or global singleton."""
    # Try to get from server context first
    if ctx and hasattr(ctx, "server") and hasattr(ctx.server, "memory"):
        return ctx.server.memory

    # Fall back to global singleton
    try:
        from services.memory_abstraction import get_memory_interface

        return get_memory_interface()
    except ImportError:
        return None


def _parse_sources(sources_str: str | None) -> list | None:
    """Parse sources string into list of SourceFilter objects."""
    if not sources_str:
        return None

    try:
        from services.memory_abstraction import SourceFilter

        # Try JSON first
        if sources_str.startswith("["):
            data = json.loads(sources_str)
            return [SourceFilter.from_dict(s) if isinstance(s, dict) else SourceFilter(name=s) for s in data]

        # Simple comma-separated list
        names = [s.strip() for s in sources_str.split(",") if s.strip()]
        return [SourceFilter(name=name) for name in names]

    except Exception as e:
        logger.warning(f"Failed to parse sources: {e}")
        return None


def register_tools(server: "FastMCP") -> int:
    """Register unified memory tools."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def memory_ask(
        question: str,
        sources: str | None = None,
        include_slow: bool = False,
        ctx: Context = None,
    ) -> str:
        """Query memory across all sources with intelligent routing.

        This is the PRIMARY way to access memory. It automatically selects
        the best sources based on your question's intent.

        **Source Latency Classes:**
        - **Fast** (<2s): yaml, code, slack - local operations, used in bootstrap
        - **Slow** (>2s): inscope, jira, gitlab, github, calendar, gmail, gdrive - external APIs

        By default, only fast sources are queried unless you specify sources explicitly
        or set include_slow=True.

        Args:
            question: Natural language question (e.g., "What am I working on?",
                     "Show me the billing code", "What did we discuss about RDS?")
            sources: Optional sources to query. Can be:
                    - Comma-separated: "code,slack,yaml"
                    - JSON array: '["code", {"name": "slack", "limit": 3}]'
                    If not specified, sources are auto-selected based on intent.
            include_slow: If True and sources is None, include slow sources in auto-routing.
                         Default False to keep queries fast.

        Returns:
            Markdown-formatted results grouped by source, with intent analysis.

        Examples:
            # Auto-select fast sources based on intent
            memory_ask("What am I working on?")
            # -> Queries yaml (current_work)

            memory_ask("Where is the billing calculation?")
            # -> Queries code search

            # Include slow sources for comprehensive results
            memory_ask("How do I configure RDS?", include_slow=True)
            # -> Queries inscope, code, yaml

            # Explicit slow sources
            memory_ask("What's the status of AAP-12345?", sources="jira")
            memory_ask("Konflux documentation", sources="inscope")
        """
        memory = _get_memory_interface(ctx)
        if not memory:
            return "❌ Memory interface not available. Server may not be fully initialized."

        try:
            # Parse sources if provided
            source_filters = _parse_sources(sources)

            # If no explicit sources and include_slow is False, use only fast sources
            if source_filters is None and not include_slow:
                try:
                    from services.memory_abstraction.registry import ADAPTER_MANIFEST

                    fast_sources = ADAPTER_MANIFEST.list_fast_adapters(capability="query")
                    if fast_sources:
                        from services.memory_abstraction import SourceFilter

                        source_filters = [SourceFilter(name=s) for s in fast_sources]
                        logger.debug(f"Using fast sources only: {fast_sources}")
                except ImportError:
                    pass  # Fall back to all sources

            # Query memory
            result = await memory.query(
                question=question,
                sources=source_filters,
            )

            # Format as markdown
            output = memory.format(result)

            # Add hint about slow sources if not included
            if not include_slow and source_filters is not None:
                output += (
                    "\n\n---\n💡 *Tip: For external data (Jira, GitLab, InScope docs),"
                    " use `include_slow=True` or specify sources explicitly.*"
                )

            return output

        except Exception as e:
            logger.error(f"memory_query failed: {e}", exc_info=True)
            return f"❌ Query failed: {e}"

    @auto_heal()
    @registry.tool()
    async def memory_search(
        query: str,
        sources: str | None = None,
        limit: int = 10,
        ctx: Context = None,
    ) -> str:
        """Semantic search across memory sources.

        Similar to memory_query but optimized for finding specific items
        rather than answering questions.

        Args:
            query: Search query
            sources: Optional sources to search (comma-separated or JSON)
            limit: Maximum results per source (default 10)

        Returns:
            Markdown-formatted search results.

        Examples:
            memory_search("billing calculation")
            memory_search("ClowdApp configuration", sources="code,inscope")
        """
        memory = _get_memory_interface(ctx)
        if not memory:
            return "❌ Memory interface not available."

        try:
            source_filters = _parse_sources(sources)

            result = await memory.search(
                query=query,
                sources=source_filters,
                limit=limit,
            )

            return memory.format(result)

        except Exception as e:
            logger.error(f"memory_search failed: {e}", exc_info=True)
            return f"❌ Search failed: {e}"

    @auto_heal()
    @registry.tool()
    async def memory_store(
        key: str,
        value: str,
        source: str = "yaml",
        ctx: Context = None,
    ) -> str:
        """Store data in memory.

        Args:
            key: Storage key (e.g., "state/current_work", "learned/patterns")
            value: Data to store (JSON string for structured data)
            source: Target source (default "yaml")

        Returns:
            Confirmation message.

        Examples:
            memory_store("state/current_work", '{"active_issues": []}')
            memory_store("learned/patterns", '{"pattern": "...", "fix": "..."}')
        """
        memory = _get_memory_interface(ctx)
        if not memory:
            return "❌ Memory interface not available."

        try:
            # Parse value as JSON if possible
            try:
                parsed_value = json.loads(value)
            except json.JSONDecodeError:
                parsed_value = value

            result = await memory.store(
                key=key,
                value=parsed_value,
                source=source,
            )

            if result.error:
                return f"❌ Store failed: {result.error}"

            return f"✅ Stored to {key} in {source}"

        except Exception as e:
            logger.error(f"memory_store failed: {e}", exc_info=True)
            return f"❌ Store failed: {e}"

    @auto_heal()
    @registry.tool()
    async def memory_health(ctx: Context = None) -> str:
        """Check health of all memory adapters.

        Returns:
            JSON with health status of each adapter.
        """
        memory = _get_memory_interface(ctx)
        if not memory:
            return json.dumps({"error": "Memory interface not available"})

        try:
            health = await memory.health_check()
            return json.dumps(health, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e)})

    @auto_heal()
    @registry.tool()
    async def memory_list_adapters(ctx: Context = None) -> str:
        """List available memory adapters with their latency classes.

        **Latency Classes:**
        - **fast**: Local operations (<2s) - used in bootstrap and default queries
        - **slow**: External APIs (>2s) - require explicit request or include_slow=True

        Returns:
            JSON with adapter names, capabilities, and latency classes.
        """
        memory = _get_memory_interface(ctx)
        if not memory:
            return json.dumps({"error": "Memory interface not available"})

        try:
            fast_adapters = []
            slow_adapters = []

            for name in memory.list_adapters():
                info = memory.get_adapter_info(name)
                if info:
                    adapter_info = {
                        "name": info.name,
                        "display_name": info.display_name,
                        "capabilities": list(info.capabilities),
                        "priority": info.priority,
                        "latency_class": getattr(info, "latency_class", "fast"),
                    }

                    if getattr(info, "latency_class", "fast") == "fast":
                        fast_adapters.append(adapter_info)
                    else:
                        slow_adapters.append(adapter_info)

            return json.dumps(
                {
                    "fast_adapters": {
                        "description": "Local operations (<2s) - used in bootstrap",
                        "count": len(fast_adapters),
                        "adapters": fast_adapters,
                    },
                    "slow_adapters": {
                        "description": "External APIs (>2s) - require explicit request",
                        "count": len(slow_adapters),
                        "adapters": slow_adapters,
                    },
                    "total_count": len(fast_adapters) + len(slow_adapters),
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)})

    return registry.count
