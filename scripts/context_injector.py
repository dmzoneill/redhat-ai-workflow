#!/usr/bin/env python3
"""
Context Injector - Gather knowledge from multiple sources for AI responses.

This module provides context injection for the Slack persona by gathering
relevant information from:
1. Slack vector DB (past conversations)
2. Code vector DB (relevant source code)
3. Jira (issue details if keys detected)
4. Memory (current work, learned patterns)

The gathered context is formatted for injection into Claude's system prompt,
enabling the AI to provide informed, contextual responses.

Usage:
    from scripts.context_injector import ContextInjector

    injector = ContextInjector()
    context = await injector.gather_context(
        query="How does billing work?",
        include_slack=True,
        include_code=True,
        include_jira=True,
    )

    # context["formatted"] contains the ready-to-inject prompt section
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Add project root to path (only when running as script)
PROJECT_ROOT = Path(__file__).parent.parent
if __name__ == "__main__":
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    if str(PROJECT_ROOT / "tool_modules") not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT / "tool_modules"))

logger = logging.getLogger(__name__)

# Display/truncation limits
PREVIEW_LENGTH = 300  # Characters for content previews
ERROR_SNIPPET_LENGTH = 100  # Characters for error messages
RESPONSE_MAX_LENGTH = 1000  # Characters for LLM responses
PATTERN_DISPLAY_LENGTH = 100  # Characters for pattern/fix display
CONTEXT_TIMEOUT_SECS = 30  # Timeout for context gathering operations


@dataclass
class ContextSource:
    """Result from a context source."""

    source: str
    found: bool
    count: int
    results: list[dict[str, Any]]
    error: Optional[str] = None
    latency_ms: float = 0.0


@dataclass
class GatheredContext:
    """All gathered context from multiple sources."""

    query: str
    sources: list[ContextSource] = field(default_factory=list)
    total_results: int = 0
    total_latency_ms: float = 0.0
    formatted: str = ""  # Ready-to-inject prompt section

    def has_context(self) -> bool:
        """Check if any context was gathered."""
        return self.total_results > 0

    def get_source(self, name: str) -> Optional[ContextSource]:
        """Get a specific source by name."""
        for src in self.sources:
            if src.source == name:
                return src
        return None


class ContextInjector:
    """
    Gathers context from multiple sources for AI persona responses.

    This class is the central point for context injection. It queries
    various knowledge sources and formats the results for injection
    into the AI's system prompt.
    """

    def __init__(
        self,
        project: str = "automation-analytics-backend",
        slack_limit: int = 5,
        code_limit: int = 5,
        jira_limit: int = 3,
        memory_limit: int = 3,
        inscope_limit: int = 1,
    ):
        self.project = project
        self.slack_limit = slack_limit
        self.code_limit = code_limit
        self.jira_limit = jira_limit
        self.memory_limit = memory_limit
        self.inscope_limit = inscope_limit

        # Track what's available
        self._slack_available: Optional[bool] = None
        self._code_available: Optional[bool] = None
        self._jira_available: Optional[bool] = None
        self._inscope_available: Optional[bool] = None

    def _check_slack_available(self) -> bool:
        """Check if Slack persona vector search is available."""
        if self._slack_available is not None:
            return self._slack_available
        try:
            from tool_modules.aa_slack_persona.src.sync import (  # noqa: F401
                SlackPersonaSync,
            )

            self._slack_available = True
        except ImportError:
            self._slack_available = False
            logger.debug("Slack persona module not available")
        return self._slack_available

    def _check_code_available(self) -> bool:
        """Check if code search is available."""
        if self._code_available is not None:
            return self._code_available
        try:
            from tool_modules.aa_code_search.src.tools_basic import (  # noqa: F401
                _search_code,
            )

            self._code_available = True
        except ImportError:
            self._code_available = False
            logger.debug("Code search module not available")
        return self._code_available

    def _check_inscope_available(self) -> bool:
        """Check if InScope AI assistant is available."""
        if self._inscope_available is not None:
            return self._inscope_available
        try:
            # Also check if we have auth configured
            import asyncio

            from tool_modules.aa_inscope.src.tools_basic import (  # noqa: F401
                _get_auth_token,
                _inscope_ask_impl,
            )

            token = asyncio.get_event_loop().run_until_complete(_get_auth_token())
            self._inscope_available = token is not None
            if not self._inscope_available:
                logger.debug("InScope available but not authenticated")
        except ImportError:
            self._inscope_available = False
            logger.debug("InScope module not available")
        except Exception as e:
            self._inscope_available = False
            logger.debug(f"InScope check failed: {e}")
        return self._inscope_available

    def _search_slack(self, query: str) -> ContextSource:
        """Search Slack persona vector store for relevant past conversations."""
        start = time.time()

        if not self._check_slack_available():
            return ContextSource(
                source="slack",
                found=False,
                count=0,
                results=[],
                error="Slack persona module not available",
            )

        try:
            from tool_modules.aa_slack_persona.src.sync import SlackPersonaSync

            sync = SlackPersonaSync()
            results = sync.search(
                query=query,
                limit=self.slack_limit,
                my_messages_only=False,  # Include all messages for knowledge
            )

            if not results:
                return ContextSource(
                    source="slack",
                    found=False,
                    count=0,
                    results=[],
                    latency_ms=(time.time() - start) * 1000,
                )

            # Format results
            formatted = []
            for msg in results:
                score = 1 - msg.get("score", 0)  # Convert distance to similarity
                formatted.append(
                    {
                        "text": msg.get("text", "")[:400],
                        "user": msg.get("user_name") or msg.get("user_id", "unknown"),
                        "channel_type": msg.get("channel_type", "unknown"),
                        "datetime": msg.get("datetime_str", ""),
                        "relevance": round(score * 100, 1),
                    }
                )

            return ContextSource(
                source="slack",
                found=True,
                count=len(formatted),
                results=formatted,
                latency_ms=(time.time() - start) * 1000,
            )

        except Exception as e:
            logger.warning(f"Slack search failed: {e}")
            return ContextSource(
                source="slack",
                found=False,
                count=0,
                results=[],
                error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    def _search_code(self, query: str) -> ContextSource:
        """Search code vector store for relevant code snippets."""
        start = time.time()

        if not self._check_code_available():
            return ContextSource(
                source="code",
                found=False,
                count=0,
                results=[],
                error="Code search module not available",
            )

        try:
            from tool_modules.aa_code_search.src.tools_basic import (
                _get_index_stats,
                _search_code,
            )

            # Check if project is indexed
            stats = _get_index_stats(self.project)
            if not stats.get("indexed"):
                return ContextSource(
                    source="code",
                    found=False,
                    count=0,
                    results=[],
                    error=f"Project '{self.project}' not indexed",
                    latency_ms=(time.time() - start) * 1000,
                )

            results = _search_code(
                query=query,
                project=self.project,
                limit=self.code_limit,
                auto_update=False,
            )

            if not results or (results and "error" in results[0]):
                error = results[0].get("error") if results else "No results"
                return ContextSource(
                    source="code",
                    found=False,
                    count=0,
                    results=[],
                    error=error,
                    latency_ms=(time.time() - start) * 1000,
                )

            # Format results
            formatted = []
            for r in results:
                formatted.append(
                    {
                        "file": r.get("file_path", ""),
                        "lines": f"{r.get('start_line', 0)}-{r.get('end_line', 0)}",
                        "type": r.get("type", "unknown"),
                        "name": r.get("name", "unknown"),
                        "relevance": round(r.get("similarity", 0) * 100, 1),
                        "preview": r.get("content", "")[:PREVIEW_LENGTH],
                    }
                )

            return ContextSource(
                source="code",
                found=True,
                count=len(formatted),
                results=formatted,
                latency_ms=(time.time() - start) * 1000,
            )

        except Exception as e:
            logger.warning(f"Code search failed: {e}")
            return ContextSource(
                source="code",
                found=False,
                count=0,
                results=[],
                error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    def _extract_jira_keys(self, text: str) -> list[str]:
        """Extract Jira issue keys from text."""
        pattern = r"\b([A-Z]{2,10}-\d+)\b"
        return list(set(re.findall(pattern, text)))

    def _search_jira(self, query: str, issue_keys: list[str]) -> ContextSource:
        """Get Jira context for detected issue keys."""
        start = time.time()

        if not issue_keys:
            return ContextSource(
                source="jira",
                found=False,
                count=0,
                results=[],
                error="No issue keys detected",
                latency_ms=(time.time() - start) * 1000,
            )

        try:
            # Try to use rh-issue CLI for Jira lookup
            rh_issue = os.getenv("RH_ISSUE_CLI", "rh-issue")
            results = []

            for key in issue_keys[: self.jira_limit]:
                try:
                    # Clear virtualenv to allow pipenv commands
                    env = os.environ.copy()
                    for var in ["VIRTUAL_ENV", "PIPENV_ACTIVE", "PYTHONHOME"]:
                        env.pop(var, None)
                    env["PIPENV_IGNORE_VIRTUALENVS"] = "1"

                    result = subprocess.run(
                        [rh_issue, "view", key, "--format", "json"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        env=env,
                    )

                    if result.returncode == 0:
                        issue_data = json.loads(result.stdout)
                        results.append(
                            {
                                "key": key,
                                "summary": issue_data.get("summary", "")[:200],
                                "status": issue_data.get("status", "unknown"),
                                "type": issue_data.get("issuetype", "unknown"),
                                "assignee": issue_data.get("assignee", "unassigned"),
                            }
                        )
                    else:
                        results.append(
                            {
                                "key": key,
                                "status": "lookup_failed",
                                "error": (
                                    result.stderr[:ERROR_SNIPPET_LENGTH]
                                    if result.stderr
                                    else "Unknown error"
                                ),
                            }
                        )

                except subprocess.TimeoutExpired:
                    results.append(
                        {
                            "key": key,
                            "status": "timeout",
                        }
                    )
                except json.JSONDecodeError:
                    # rh-issue might not support --format json, try plain
                    results.append(
                        {
                            "key": key,
                            "status": "detected",
                            "note": "Plain text format",
                        }
                    )

            return ContextSource(
                source="jira",
                found=len(results) > 0,
                count=len(results),
                results=results,
                latency_ms=(time.time() - start) * 1000,
            )

        except Exception as e:
            logger.warning(f"Jira lookup failed: {e}")
            return ContextSource(
                source="jira",
                found=False,
                count=0,
                results=[{"key": k, "status": "detected"} for k in issue_keys],
                error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    def _search_memory(self, query: str) -> ContextSource:
        """Search memory for relevant patterns and current work."""
        start = time.time()

        try:
            from scripts.common.memory import read_memory

            results = []

            # Check current work
            current_work = read_memory("state/current_work")
            if current_work:
                active_issues = current_work.get("active_issues", [])
                if active_issues:
                    results.append(
                        {
                            "type": "active_issues",
                            "items": [i.get("key", str(i)) for i in active_issues[:3]],
                        }
                    )

                current_branch = current_work.get("current_branch")
                if current_branch:
                    results.append(
                        {
                            "type": "current_branch",
                            "value": current_branch,
                        }
                    )

            # Check learned patterns for relevant fixes
            patterns = read_memory("learned/patterns")
            if patterns:
                # Simple keyword matching for relevant patterns
                query_lower = query.lower()
                relevant_patterns = []
                for p in patterns.get("patterns", [])[:10]:
                    pattern_text = p.get("pattern", "").lower()
                    if any(word in pattern_text for word in query_lower.split()):
                        relevant_patterns.append(
                            {
                                "pattern": p.get("pattern", "")[
                                    :PATTERN_DISPLAY_LENGTH
                                ],
                                "fix": p.get("fix", "")[:PATTERN_DISPLAY_LENGTH],
                            }
                        )

                if relevant_patterns:
                    results.append(
                        {
                            "type": "learned_patterns",
                            "items": relevant_patterns[:2],
                        }
                    )

            return ContextSource(
                source="memory",
                found=len(results) > 0,
                count=len(results),
                results=results,
                latency_ms=(time.time() - start) * 1000,
            )

        except ImportError:
            return ContextSource(
                source="memory",
                found=False,
                count=0,
                results=[],
                error="Memory module not available",
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            logger.warning(f"Memory search failed: {e}")
            return ContextSource(
                source="memory",
                found=False,
                count=0,
                results=[],
                error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    def _search_inscope(self, query: str) -> ContextSource:
        """Query InScope AI assistants for domain-specific knowledge.

        InScope provides AI assistants trained on Red Hat internal documentation
        including App Interface, Clowder, Konflux, and other services.
        """
        start = time.time()

        if not self._check_inscope_available():
            return ContextSource(
                source="inscope",
                found=False,
                count=0,
                results=[],
                error="InScope not available or not authenticated",
                latency_ms=(time.time() - start) * 1000,
            )

        try:
            import asyncio

            from tool_modules.aa_inscope.src.tools_basic import _inscope_ask_impl

            # Run the async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result_json = loop.run_until_complete(
                    _inscope_ask_impl(
                        query=query,
                        timeout_secs=CONTEXT_TIMEOUT_SECS,
                        include_sources=True,
                    )
                )
            finally:
                loop.close()

            result = json.loads(result_json)

            if not result.get("success"):
                return ContextSource(
                    source="inscope",
                    found=False,
                    count=0,
                    results=[],
                    error=result.get("error", "Unknown error"),
                    latency_ms=(time.time() - start) * 1000,
                )

            # Format the result
            formatted = [
                {
                    "assistant": result.get("assistant", "unknown"),
                    "assistant_id": result.get("assistant_id", 0),
                    "response": result.get("response", "")[:RESPONSE_MAX_LENGTH],
                    "sources": result.get("sources", [])[:3],  # Top 3 sources
                }
            ]

            return ContextSource(
                source="inscope",
                found=True,
                count=1,
                results=formatted,
                latency_ms=(time.time() - start) * 1000,
            )

        except Exception as e:
            logger.warning(f"InScope query failed: {e}")
            return ContextSource(
                source="inscope",
                found=False,
                count=0,
                results=[],
                error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    def _format_context(self, context: GatheredContext) -> str:
        """Format gathered context for injection into system prompt."""
        if not context.has_context():
            return ""

        sections = []

        # Slack context
        slack_src = context.get_source("slack")
        if slack_src and slack_src.found:
            lines = ["## Relevant Slack Conversations", ""]
            for msg in slack_src.results[:5]:
                user = msg.get("user", "unknown")
                relevance = msg.get("relevance", 0)
                text = msg.get("text", "")
                dt = msg.get("datetime", "")
                lines.append(f"**{user}** ({dt}, {relevance}% relevant):")
                lines.append(f"> {text}")
                lines.append("")
            sections.append("\n".join(lines))

        # Code context
        code_src = context.get_source("code")
        if code_src and code_src.found:
            lines = ["## Relevant Code", ""]
            for r in code_src.results[:5]:
                file_path = r.get("file", "")
                line_range = r.get("lines", "")
                name = r.get("name", "")
                relevance = r.get("relevance", 0)
                preview = r.get("preview", "")
                lines.append(
                    f"**{name}** in `{file_path}:{line_range}` ({relevance}% relevant):"
                )
                lines.append(f"```\n{preview}\n```")
                lines.append("")
            sections.append("\n".join(lines))

        # Jira context
        jira_src = context.get_source("jira")
        if jira_src and jira_src.found:
            lines = ["## Related Jira Issues", ""]
            for issue in jira_src.results[:3]:
                key = issue.get("key", "")
                summary = issue.get("summary", "")
                status = issue.get("status", "")
                if summary:
                    lines.append(f"- **{key}**: {summary} (Status: {status})")
                else:
                    lines.append(f"- **{key}**: (detected in query)")
            sections.append("\n".join(lines))

        # Memory context
        memory_src = context.get_source("memory")
        if memory_src and memory_src.found:
            lines = ["## Current Work Context", ""]
            for item in memory_src.results:
                item_type = item.get("type", "")
                if item_type == "active_issues":
                    issues = ", ".join(item.get("items", []))
                    lines.append(f"- Active issues: {issues}")
                elif item_type == "current_branch":
                    lines.append(f"- Current branch: {item.get('value', '')}")
                elif item_type == "learned_patterns":
                    lines.append("- Relevant patterns:")
                    for p in item.get("items", []):
                        lines.append(f"  - {p.get('pattern', '')} → {p.get('fix', '')}")
            sections.append("\n".join(lines))

        # InScope AI context
        inscope_src = context.get_source("inscope")
        if inscope_src and inscope_src.found:
            lines = ["## InScope AI Knowledge", ""]
            for r in inscope_src.results:
                assistant = r.get("assistant", "unknown")
                response = r.get("response", "")
                sources = r.get("sources", [])

                lines.append(f"**From {assistant}:**")
                lines.append("")
                lines.append(response)
                lines.append("")

                if sources:
                    lines.append("*Sources:*")
                    for src in sources[:3]:
                        title = src.get("title", "")
                        url = src.get("url", "")
                        if title:
                            lines.append(f"- [{title}]({url})" if url else f"- {title}")
                    lines.append("")
            sections.append("\n".join(lines))

        if not sections:
            return ""

        header = (
            f"# Knowledge Context (gathered in {context.total_latency_ms:.0f}ms)\n\n"
        )
        return header + "\n\n".join(sections)

    def gather_context(
        self,
        query: str,
        include_slack: bool = True,
        include_code: bool = True,
        include_jira: bool = True,
        include_memory: bool = True,
        include_inscope: bool = True,
    ) -> GatheredContext:
        """
        Gather context from all enabled sources.

        Args:
            query: The user's question/message
            include_slack: Search Slack persona vector DB
            include_code: Search code vector DB
            include_jira: Look up detected Jira issue keys
            include_memory: Check memory for current work context
            include_inscope: Query InScope AI assistants for documentation

        Returns:
            GatheredContext with all results and formatted prompt section
        """
        start = time.time()
        sources = []

        # Extract Jira keys early (needed for Jira lookup)
        jira_keys = self._extract_jira_keys(query)

        # Gather from each source
        if include_slack:
            sources.append(self._search_slack(query))

        if include_code:
            sources.append(self._search_code(query))

        if include_jira:
            sources.append(self._search_jira(query, jira_keys))

        if include_memory:
            sources.append(self._search_memory(query))

        if include_inscope:
            sources.append(self._search_inscope(query))

        # Build result
        total_results = sum(s.count for s in sources)
        total_latency = (time.time() - start) * 1000

        context = GatheredContext(
            query=query,
            sources=sources,
            total_results=total_results,
            total_latency_ms=total_latency,
        )

        # Format for injection
        context.formatted = self._format_context(context)

        logger.info(
            f"Context gathered: {total_results} results from "
            f"{len([s for s in sources if s.found])} sources in {total_latency:.0f}ms"
        )

        return context

    async def gather_context_async(
        self,
        query: str,
        include_slack: bool = True,
        include_code: bool = True,
        include_jira: bool = True,
        include_memory: bool = True,
        include_inscope: bool = True,
        thread_context: list[dict] | None = None,
    ) -> GatheredContext:
        """
        Async version of gather_context.

        Runs searches in parallel for better performance.

        Args:
            query: The user's question/message
            include_slack: Search Slack persona vector DB
            include_code: Search code vector DB
            include_jira: Look up detected Jira issue keys
            include_memory: Check memory for current work context
            include_inscope: Query InScope AI assistants for documentation
            thread_context: Optional list of previous messages in thread (for Slack)
        """
        # For now, just wrap the sync version
        # TODO: Make individual searches async for true parallelism
        return await asyncio.to_thread(
            self.gather_context,
            query,
            include_slack,
            include_code,
            include_jira,
            include_memory,
            include_inscope,
        )

    async def gather_context_unified(
        self,
        query: str,
        sources: list[str] | None = None,
        thread_context: list[dict] | None = None,
    ) -> GatheredContext:
        """
        Gather context using the unified memory abstraction layer.

        This is the NEW recommended way to gather context. It uses the
        memory abstraction layer which provides:
        - Intelligent intent-based source selection
        - Parallel query execution
        - Unified result formatting

        Args:
            query: The user's question/message
            sources: Optional list of sources to query (e.g., ["code", "slack"])
                    If None, sources are auto-selected based on intent.
            thread_context: Optional list of previous messages in thread

        Returns:
            GatheredContext with all results and formatted prompt section
        """
        start = time.time()

        try:
            from services.memory_abstraction import (
                MemoryInterface,
                SourceFilter,
                get_memory_interface,
            )

            # Get or create memory interface
            try:
                memory = get_memory_interface()
            except Exception:
                # Fall back to creating a new instance
                memory = MemoryInterface()

            # Build source filters
            source_filters = None
            if sources:
                source_filters = [
                    SourceFilter(name=s, project=self.project) for s in sources
                ]

            # Query memory abstraction
            result = await memory.query(
                question=query,
                sources=source_filters,
                thread_context=thread_context,
            )

            # Convert to GatheredContext format
            context_sources = []
            for source_name in result.sources_queried:
                items = result.get_items_by_source(source_name)
                context_sources.append(
                    ContextSource(
                        source=source_name,
                        found=len(items) > 0,
                        count=len(items),
                        results=[item.to_dict() for item in items],
                        error=result.errors.get(source_name),
                    )
                )

            total_latency = (time.time() - start) * 1000

            context = GatheredContext(
                query=query,
                sources=context_sources,
                total_results=result.total_count,
                total_latency_ms=total_latency,
            )

            # Use the memory abstraction's formatter
            context.formatted = memory.format(result)

            logger.info(
                f"Unified context gathered: {result.total_count} results from "
                f"{len(result.sources_queried)} sources in {total_latency:.0f}ms"
            )

            return context

        except ImportError as e:
            logger.warning(f"Memory abstraction not available: {e}")
            # Fall back to legacy method
            return await self.gather_context_async(query)
        except Exception as e:
            logger.error(f"Unified context gathering failed: {e}", exc_info=True)
            # Fall back to legacy method
            return await self.gather_context_async(query)


# Convenience function
def get_context_for_query(
    query: str, project: str = "automation-analytics-backend"
) -> str:
    """
    Quick way to get formatted context for a query.

    Returns the formatted context string ready for injection.
    """
    injector = ContextInjector(project=project)
    context = injector.gather_context(query)
    return context.formatted


if __name__ == "__main__":
    # Test the context injector
    import argparse

    parser = argparse.ArgumentParser(description="Test context injection")
    parser.add_argument("--query", required=True, help="Query to test")
    parser.add_argument(
        "--project", default="automation-analytics-backend", help="Project name"
    )
    args = parser.parse_args()

    injector = ContextInjector(project=args.project)
    context = injector.gather_context(args.query)

    print(f"Query: {context.query}")
    print(f"Total results: {context.total_results}")
    print(f"Latency: {context.total_latency_ms:.0f}ms")
    print("\nSources:")
    for src in context.sources:
        status = "✓" if src.found else "✗"
        print(f"  {status} {src.source}: {src.count} results ({src.latency_ms:.0f}ms)")
        if src.error:
            print(f"      Error: {src.error}")

    print(f"\n{'=' * 60}")
    print("FORMATTED CONTEXT:")
    print("=" * 60)
    print(context.formatted or "(no context gathered)")
