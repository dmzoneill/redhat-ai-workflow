"""
InScope Memory Adapter - Memory source for InScope AI assistants.

This adapter exposes InScope AI assistants as a memory source,
allowing the memory abstraction layer to query Red Hat's domain-specific
AI assistants for documentation and knowledge.

It wraps the existing inscope_ask/inscope_query functionality.
"""

import json
import logging
from typing import Any

from services.memory_abstraction.models import (
    AdapterResult,
    HealthStatus,
    MemoryItem,
    SourceFilter,
)
from services.memory_abstraction.registry import memory_adapter

logger = logging.getLogger(__name__)


@memory_adapter(
    name="inscope",
    display_name="InScope AI",
    capabilities={"query"},
    intent_keywords=[
        "rds",
        "database",
        "clowder",
        "clowdapp",
        "konflux",
        "release",
        "app-interface",
        "deploy",
        "namespace",
        "saas",
        "vault",
        "secret",
        "terraform",
        "aws",
        "s3",
        "prometheus",
        "alertmanager",
        "grafana",
        "monitoring",
        "incident",
        "outage",
        "postmortem",
        "pagerduty",
        "documentation",
        "how to",
        "configure",
        "setup",
    ],
    priority=40,  # Lower priority - use for documentation queries
    latency_class="slow",  # External AI API (2-120s)
)
class InScopeAdapter:
    """
    Adapter for InScope AI assistants.

    Provides access to Red Hat's domain-specific AI assistants
    trained on internal documentation.
    """

    async def query(
        self,
        question: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """
        Query InScope AI assistants.

        Args:
            question: Question to ask
            filter: Optional filter with assistant name in extra

        Returns:
            AdapterResult with AI response
        """
        try:
            # Import the existing inscope implementation
            from tool_modules.aa_inscope.src.tools_basic import (
                _inscope_ask_impl,
                _inscope_query_impl,
            )

            # Get assistant from filter if specified
            assistant = None
            if filter and filter.extra:
                assistant = filter.extra.get("assistant")

            # Query InScope
            if assistant:
                result_json = await _inscope_query_impl(
                    query=question,
                    assistant=assistant,
                    timeout_secs=120,
                    include_sources=True,
                )
            else:
                # Auto-select assistant based on query
                result_json = await _inscope_ask_impl(
                    query=question,
                    timeout_secs=120,
                    include_sources=True,
                )

            # Parse result
            result = json.loads(result_json)

            if not result.get("success"):
                error_msg = result.get("error", "InScope query failed")

                # Check if it's an auth error and try auto-login
                if "auth" in error_msg.lower() or "token" in error_msg.lower():
                    logger.info("Auth error detected, attempting auto-login...")
                    try:
                        from tool_modules.aa_inscope.src.tools_basic import (
                            _inscope_auto_login_impl,
                        )

                        login_result = await _inscope_auto_login_impl(headless=True)
                        login_data = json.loads(login_result)
                        if login_data.get("success"):
                            # Retry the query
                            logger.info("Auto-login successful, retrying query...")
                            if assistant:
                                result_json = await _inscope_query_impl(
                                    query=question,
                                    assistant=assistant,
                                    timeout_secs=120,
                                    include_sources=True,
                                )
                            else:
                                result_json = await _inscope_ask_impl(
                                    query=question,
                                    timeout_secs=120,
                                    include_sources=True,
                                )
                            result = json.loads(result_json)
                            if result.get("success"):
                                item = self._to_memory_item(result)
                                return AdapterResult(
                                    source="inscope",
                                    items=[item],
                                )
                    except Exception as e:
                        logger.warning(f"Auto-login failed: {e}")

                return AdapterResult(
                    source="inscope",
                    items=[],
                    error=error_msg,
                )

            # Convert to MemoryItem
            item = self._to_memory_item(result)

            return AdapterResult(
                source="inscope",
                items=[item],
            )

        except ImportError as e:
            logger.error(f"InScope module not available: {e}")
            return AdapterResult(
                source="inscope",
                items=[],
                error="InScope module not available",
            )
        except Exception as e:
            logger.error(f"InScope query failed: {e}")
            return AdapterResult(
                source="inscope",
                items=[],
                error=str(e),
            )

    async def search(
        self,
        query: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Search is the same as query for InScope."""
        return await self.query(query, filter)

    async def store(
        self,
        key: str,
        value: Any,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """InScope is read-only."""
        return AdapterResult(
            source="inscope",
            items=[],
            error="InScope is read-only",
        )

    async def health_check(self) -> HealthStatus:
        """Check if InScope is available."""
        try:
            from tool_modules.aa_inscope.src.tools_basic import (
                _inscope_auth_status_impl,
            )

            status_json = await _inscope_auth_status_impl()
            status = json.loads(status_json)

            return HealthStatus(
                healthy=status.get("authenticated", False),
                details={
                    "has_token": status.get("has_token", False),
                    "token_expired": status.get("token_expired", True),
                },
                error="Not authenticated" if not status.get("authenticated") else None,
            )
        except ImportError:
            return HealthStatus(
                healthy=False,
                error="InScope module not available",
            )
        except Exception as e:
            return HealthStatus(healthy=False, error=str(e))

    def _to_memory_item(self, result: dict) -> MemoryItem:
        """Convert InScope result to MemoryItem."""
        assistant = result.get("assistant", "InScope")
        response = result.get("response", "")
        sources = result.get("sources", [])

        # Build summary
        summary = f"Response from {assistant}"

        # Build content with sources
        content = response
        if sources:
            content += "\n\n**Sources:**\n"
            for source in sources[:3]:
                title = source.get("title", "Unknown")
                url = source.get("url", "")
                if url:
                    content += f"- [{title}]({url})\n"
                else:
                    content += f"- {title}\n"

        return MemoryItem(
            source="inscope",
            type="document",
            relevance=0.8,  # InScope responses are generally relevant
            summary=summary,
            content=content,
            metadata={
                "assistant": assistant,
                "assistant_id": result.get("assistant_id"),
                "query": result.get("query", ""),
                "sources": sources,
            },
        )
