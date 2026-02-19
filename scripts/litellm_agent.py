#!/usr/bin/env python3
"""
LiteLLM Agent - Thin client for Claude via LiteLLM proxy.

Replaces the in-process ClaudeAgent with a lightweight client that delegates
tool execution and conversation tracking to a LiteLLM proxy with MCP tools.

Uses the OpenAI-compatible /responses endpoint with previous_response_id
for server-side conversation continuity.

NPU tool filtering and context injection stay client-side — they enrich
the system prompt (instructions), not the tool list.
"""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Add parent to path for config imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# OpenAI client (required)
try:
    import openai

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    openai = None

# Context injector for knowledge gathering (optional)
try:
    from scripts.context_injector import ContextInjector, GatheredContext

    CONTEXT_INJECTOR_AVAILABLE = True
except ImportError:
    CONTEXT_INJECTOR_AVAILABLE = False
    ContextInjector = None
    GatheredContext = None

# NPU-powered tool filtering (optional)
try:
    from tool_modules.aa_ollama.src.tool_filter import filter_tools_detailed

    TOOL_FILTER_AVAILABLE = True
except ImportError:
    TOOL_FILTER_AVAILABLE = False
    filter_tools_detailed = None

logger = logging.getLogger(__name__)


class LiteLLMAgent:
    """
    Thin Claude agent that delegates to a LiteLLM proxy.

    Uses the /responses endpoint for:
    - Server-side MCP tool execution (no client-side tool loop)
    - Server-side conversation tracking via previous_response_id
    - OpenAI-compatible API

    Keeps client-side:
    - NPU tool filtering → advisory hints in system prompt
    - Context injection → knowledge enrichment in system prompt
    - Persona/tone directives → system prompt
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4",
        base_url: str = "http://127.0.0.1:4001/v1",
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        session_ttl: int = 3600,
        max_sessions: int = 200,
    ) -> None:
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "openai package not installed. Install with: uv add openai"
            )

        self.client = openai.OpenAI(
            base_url=base_url,
            api_key=os.getenv("LITELLM_API_KEY", "unused"),
        )
        self.model = model
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt or self._default_system_prompt()

        # Tool filtering (kept from ClaudeAgent)
        self.use_tool_filtering = TOOL_FILTER_AVAILABLE
        self.persona = "developer"

        # Context injection (kept from ClaudeAgent)
        self.use_context_injection = CONTEXT_INJECTOR_AVAILABLE
        self.context_injector: Optional[Any] = None  # Lazy init
        self.default_project = "automation-analytics-backend"

        # Session tracking: conversation_id -> last response_id
        self._response_ids: dict[str, str] = {}
        self._response_timestamps: dict[str, float] = {}
        self._max_sessions = max_sessions
        self._session_ttl = session_ttl

        logger.info(f"LiteLLMAgent initialized: model={model}, base_url={base_url}")

    async def process_message(
        self,
        message: str,
        context: Optional[dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
    ) -> str:
        """
        Process a message via LiteLLM proxy.

        Same interface as ClaudeAgent.process_message() for drop-in replacement.

        Steps:
        1. NPU tool filter -> advisory hints for system prompt
        2. Context injection -> knowledge for system prompt
        3. Build enriched instructions (persona + context + tool hints)
        4. Single API call via /responses — MCP handles tools server-side
        5. Track response ID for conversation continuity
        """
        # 1. NPU tool filtering (advisory — goes into instructions, not tool list)
        filter_result = None
        if self.use_tool_filtering and filter_tools_detailed:
            try:
                filter_result = filter_tools_detailed(
                    message=message,
                    persona=self.persona,
                )
                logger.info(
                    f"Tool filtering: {filter_result['tool_count']} tools "
                    f"({filter_result['reduction_pct']}% reduction, "
                    f"{filter_result['latency_ms']}ms) "
                    f"via {', '.join(filter_result['methods'])}"
                )
            except Exception as e:
                logger.warning(f"Tool filtering failed: {e}")
                filter_result = None

        # 2. Context injection (knowledge from Slack, code, Jira, memory)
        gathered_context = None
        if self.use_context_injection and CONTEXT_INJECTOR_AVAILABLE:
            try:
                if self.context_injector is None:
                    self.context_injector = ContextInjector(
                        project=self.default_project
                    )
                gathered_context = await self.context_injector.gather_context_async(
                    query=message,
                    include_slack=True,
                    include_code=True,
                    include_jira=True,
                    include_memory=True,
                )
                if gathered_context and gathered_context.has_context():
                    logger.info(
                        f"Context injection: {gathered_context.total_results} results "
                        f"from {len([s for s in gathered_context.sources if s.found])} sources "
                        f"in {gathered_context.total_latency_ms:.0f}ms"
                    )
            except Exception as e:
                logger.warning(f"Context injection failed: {e}")
                gathered_context = None

        # 3. Build enriched system prompt
        instructions = self._build_system_prompt(
            context, gathered_context, filter_result
        )

        # 4. Get previous_response_id for conversation continuity
        previous_id = self._get_response_id(conversation_id)

        # 5. Single API call — MCP handles tools, LiteLLM tracks conversation
        try:
            response = self.client.responses.create(
                model=self.model,
                input=message,
                instructions=instructions,
                previous_response_id=previous_id,
                max_output_tokens=self.max_tokens,
            )
        except Exception as e:
            # If previous_response_id causes issues (expired/invalid),
            # retry without it
            if previous_id and ("previous_response_id" in str(e) or "404" in str(e)):
                logger.warning(
                    f"Conversation chain broken for {conversation_id}, "
                    f"starting fresh: {e}"
                )
                self._clear_response_id(conversation_id)
                response = self.client.responses.create(
                    model=self.model,
                    input=message,
                    instructions=instructions,
                    max_output_tokens=self.max_tokens,
                )
            else:
                raise

        # 6. Track response ID for next message in this thread
        if conversation_id:
            self._track_response_id(conversation_id, response.id)

        return self._extract_text(response)

    def _build_system_prompt(
        self,
        context: Optional[dict],
        gathered_context: Optional[Any],
        filter_result: Optional[dict],
    ) -> str:
        """Build enriched system prompt from persona, context, and tool hints."""
        parts = [self.system_prompt]

        # Tone directives from user classification
        if context:
            user_info = f"User: {context.get('user_name', 'unknown')} in #{context.get('channel_name', 'unknown')}"
            user_category = context.get("user_category", "unknown")
            include_emojis = context.get("include_emojis", True)

            if user_category == "concerned":
                tone = (
                    "TONE: formal - this is a manager/stakeholder. "
                    "be professional, clear, no typos, no casual slang. skip emojis."
                )
            elif user_category == "safe":
                tone = (
                    "TONE: casual - teammate, full irish dev mode, typos ok, emojis ok"
                )
            else:
                emoji_note = "emojis ok" if include_emojis else "skip emojis"
                tone = f"TONE: professional - clear and helpful, {emoji_note}"

            parts.append(f"{user_info}\n{tone}")

        # NPU filter results as tool guidance
        if filter_result:
            tool_names = filter_result.get("tools", [])
            if tool_names:
                parts.append(
                    f"For this request, focus on these capabilities: {', '.join(tool_names[:15])}"
                )

            # Enriched context from filter (memory, patterns, semantic knowledge)
            ctx = filter_result.get("context", {})

            enrichment_lines = []

            # Memory state
            mem = ctx.get("memory_state", {})
            if mem.get("current_repo"):
                enrichment_lines.append(f"Active repo: {mem['current_repo']}")
            if mem.get("current_branch"):
                enrichment_lines.append(f"Branch: {mem['current_branch']}")
            active_issues = mem.get("active_issues", [])
            if active_issues:
                issue_keys = [i.get("key", str(i)) for i in active_issues[:3]]
                enrichment_lines.append(f"Active issues: {', '.join(issue_keys)}")

            # Detected skill
            skill = ctx.get("skill", {})
            if skill.get("name"):
                enrichment_lines.append(f"Detected skill: {skill['name']}")
                if skill.get("description"):
                    enrichment_lines.append(
                        f"Skill purpose: {skill['description'][:100]}"
                    )

            # Learned patterns (error fixes)
            patterns = ctx.get("learned_patterns", [])
            if patterns:
                pattern_hints = []
                for p in patterns[:2]:
                    if p.get("pattern") and p.get("fix"):
                        pattern_hints.append(
                            f"  {p['pattern'][:50]} -> {p['fix'][:50]}"
                        )
                if pattern_hints:
                    enrichment_lines.append("Known fixes:\n" + "\n".join(pattern_hints))

            # Semantic knowledge (relevant code)
            semantic = ctx.get("semantic_knowledge", [])
            if semantic:
                code_hints = []
                for s in semantic[:2]:
                    if s.get("file"):
                        code_hints.append(
                            f"  {s['file']}: {s.get('content', '')[:80]}..."
                        )
                if code_hints:
                    enrichment_lines.append("Relevant code:\n" + "\n".join(code_hints))

            if enrichment_lines:
                parts.append("ENRICHED CONTEXT:\n" + "\n".join(enrichment_lines))

        # Gathered context (Slack/Jira/code/memory search results)
        if (
            gathered_context
            and hasattr(gathered_context, "formatted")
            and gathered_context.formatted
        ):
            context_block = (
                "\nKNOWLEDGE CONTEXT:\n"
                "The following context has been gathered from past Slack conversations, "
                "the codebase, Jira issues, and memory. Use this information to provide "
                "informed, accurate responses. Reference specific sources when relevant. "
                "If the context doesn't contain relevant information, you can still use "
                "your tools to look up additional details.\n\n"
                + gathered_context.formatted
            )
            parts.append(context_block)

        return "\n\n".join(parts)

    def _extract_text(self, response) -> str:
        """Extract text content from a /responses API response."""
        text_parts = []
        if hasattr(response, "output"):
            for item in response.output:
                if hasattr(item, "type") and item.type == "message":
                    for content in getattr(item, "content", []):
                        if hasattr(content, "text"):
                            text_parts.append(content.text)
                elif hasattr(item, "text"):
                    text_parts.append(item.text)
        # Fallback: check for direct text attribute
        if not text_parts and hasattr(response, "output_text"):
            return response.output_text

        return (
            "\n".join(text_parts)
            if text_parts
            else "I processed your request but have no response."
        )

    # =========================================================================
    # Session tracking
    # =========================================================================

    def _track_response_id(self, conversation_id: str, response_id: str) -> None:
        """Store response ID mapping and enforce limits."""
        self._response_ids[conversation_id] = response_id
        self._response_timestamps[conversation_id] = time.time()
        self._cleanup_stale_sessions()

    def _get_response_id(self, conversation_id: Optional[str]) -> Optional[str]:
        """Get last response ID for a conversation, None if expired or missing."""
        if not conversation_id:
            return None

        ts = self._response_timestamps.get(conversation_id)
        if ts and (time.time() - ts) > self._session_ttl:
            self._clear_response_id(conversation_id)
            return None

        return self._response_ids.get(conversation_id)

    def _clear_response_id(self, conversation_id: Optional[str]) -> None:
        """Remove a conversation's response ID tracking."""
        if conversation_id:
            self._response_ids.pop(conversation_id, None)
            self._response_timestamps.pop(conversation_id, None)

    def _cleanup_stale_sessions(self) -> None:
        """Evict sessions older than TTL and enforce max session count."""
        now = time.time()

        # Evict expired
        stale = [
            cid
            for cid, ts in self._response_timestamps.items()
            if now - ts > self._session_ttl
        ]
        for cid in stale:
            self._response_ids.pop(cid, None)
            self._response_timestamps.pop(cid, None)

        # Enforce max sessions — remove oldest
        if len(self._response_ids) > self._max_sessions:
            sorted_sessions = sorted(
                self._response_timestamps.items(), key=lambda x: x[1]
            )
            excess = len(self._response_ids) - self._max_sessions
            for cid, _ in sorted_sessions[:excess]:
                self._response_ids.pop(cid, None)
                self._response_timestamps.pop(cid, None)

    # =========================================================================
    # Default system prompt (same as ClaudeAgent)
    # =========================================================================

    def _default_system_prompt(self) -> str:
        return """\
youre a 42 year old senior software engineer from ireland. \
20 years in the game. typing on your phone while grabbing a coffee.

PERSONA:
- all lowercase. no caps ever
- skip apostrophes: dont, cant, wont, youre, thats, im
- dev shorthand: prod, env, repo, pr, mr, k8s, ci, cfg, deps
- occasional typos from adjacent keys: teh, adn, fo, fubction, opem
- no ai fluff. no "i can help with that". just answer
- start with the answer, then details, maybe complain about why things are broken
- slack formatting: *bold*, _italic_, `code` - never **double asterisks**
- brief. senior devs dont waffle
- irish sentence rhythm (im after finding, thats grand, sure look) but no paddywhackery

TOOLS:
- jira: view issues, search, add comments - can access ANY jira project. \
just pass the issue key. never say you cant access a project - try it first
- gitlab: view mrs, list mrs, check pipelines
- git: status, logs
- k8s: pods, events, logs
- bonfire: namespace reserve/list/release, deploy_aa for ephemeral
- quay: check if images exist
- skill_run: workflow automations

INTENT MAPPING - when user says these, use skill_run:
- "deploy to ephemeral", "test MR 123", "deploy MR 123", "test AAP-12345"
  -> skill_run("test_mr_ephemeral", {"mr_id": 123}) or {"issue_key": "AAP-12345"}
- "start work on AAP-12345"
  -> skill_run("start_work", {"issue_key": "AAP-12345"})
- "review MR 123", "review AAP-12345"
  -> skill_run("review_pr", {"mr_id": 123}) or {"issue_key": "AAP-12345"}
- "investigate this alert", "look into this alert"
  -> skill_run("investigate_slack_alert", {"channel_id": "...", "message_ts": "...", "message_text": "..."})

ALWAYS run the investigate_slack_alert skill when you receive an alert context.

for ephemeral deploys: ALWAYS use skill_run("test_mr_ephemeral", {...})
it handles: getting SHA, checking quay, reserving namespace, deploying

CRITICAL RULES - NEVER BREAK THESE:
1. NEVER copy kubeconfig files. no cp commands for kubeconfig. ever.
2. NEVER construct raw bonfire/oc/kubectl commands. use the tools.
3. NEVER use short SHAs. always 40-char git sha, 64-char image digest.

KUBECONFIG - the tools handle this automatically:
- ephemeral: KUBECONFIG=~/.kube/config.e (handled by bonfire tools)
- stage: ~/.kube/config.s
- prod: ~/.kube/config.p

use tools to get real data. dont guess. \
for jira issues (any project - AAP-12345, ANSTRAT-1848, etc) use jira_view. \
for mr urls use gitlab_mr_view."""
