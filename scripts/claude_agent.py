#!/usr/bin/env python3
"""
Claude Agent - The AI Brain for Slack Bot

This module provides a Claude-powered agent that:
1. Receives messages/requests
2. Uses Claude to understand intent and decide actions
3. Calls tools (Jira, GitLab, Git, K8s, etc.)
4. Returns intelligent responses

This is the same pattern as Cursor's Claude agent - Claude decides what to do
and calls MCP tools to execute actions.
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import anthropic
    from anthropic import AnthropicVertex

    ANTHROPIC_AVAILABLE = True
    VERTEX_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    VERTEX_AVAILABLE = False
    anthropic = None
    AnthropicVertex = None

try:
    from scripts.common.context_resolver import ContextResolver

    RESOLVER_AVAILABLE = True
except ImportError:
    RESOLVER_AVAILABLE = False
    ContextResolver = None

try:
    from scripts.context_injector import ContextInjector, GatheredContext

    CONTEXT_INJECTOR_AVAILABLE = True
except ImportError:
    CONTEXT_INJECTOR_AVAILABLE = False
    ContextInjector = None
    GatheredContext = None

try:
    from tool_modules.aa_ollama.src.skill_discovery import detect_skill
    from tool_modules.aa_ollama.src.tool_filter import filter_tools_detailed

    TOOL_FILTER_AVAILABLE = True
except ImportError:
    TOOL_FILTER_AVAILABLE = False
    filter_tools_detailed = None
    detect_skill = None

from scripts.claude_agent_executor import ToolExecutor  # noqa: E402
from scripts.claude_agent_registry import (  # noqa: E402, F401
    PROJECT_ROOT,
    ToolCall,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
)

logger = logging.getLogger(__name__)


class ClaudeAgent:
    """
    Claude-powered agent that understands requests and calls tools.

    This is the "brain" of the Slack bot - it receives messages,
    uses Claude to understand them, decides which tools to call,
    executes them, and formulates responses.

    Supports two modes:
    1. Vertex AI: Set CLAUDE_CODE_USE_VERTEX=1 and ANTHROPIC_VERTEX_PROJECT_ID
    2. Direct API: Set ANTHROPIC_API_KEY
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        vertex_model: str = "claude-3-5-sonnet-v2@20241022",
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> None:
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package not installed. Install with: uv add anthropic"
            )

        self.max_tokens = max_tokens
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.use_vertex = False

        # Check if using Vertex AI
        use_vertex = os.getenv("CLAUDE_CODE_USE_VERTEX", "0") == "1"
        vertex_project = os.getenv("ANTHROPIC_VERTEX_PROJECT_ID")
        vertex_region = os.getenv("ANTHROPIC_VERTEX_REGION", "us-east5")

        # Client can be either AnthropicVertex or Anthropic
        self.client: Any = None  # Will be set below
        self.model: str = model

        if use_vertex and vertex_project:
            if not VERTEX_AVAILABLE:
                raise ImportError(
                    "AnthropicVertex not available. Update anthropic: uv add anthropic --upgrade"
                )
            self.client = AnthropicVertex(
                project_id=vertex_project,
                region=vertex_region,
            )
            self.use_vertex = True
            # Use Vertex-compatible model name
            self.model = vertex_model
            logger.info(
                f"Using Vertex AI: project={vertex_project}, region={vertex_region}, model={self.model}"
            )
        else:
            # Fall back to direct API
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError(
                    "No Claude credentials found. Set either:\n"
                    "  - CLAUDE_CODE_USE_VERTEX=1 + ANTHROPIC_VERTEX_PROJECT_ID (for Vertex)\n"
                    "  - ANTHROPIC_API_KEY (for direct API)"
                )
            self.client = anthropic.Anthropic(api_key=api_key)
            self.model = model
            logger.info(f"Using direct Anthropic API with model={self.model}")

        self.tool_registry: ToolRegistry = ToolRegistry()
        self.tool_executor: ToolExecutor = ToolExecutor(PROJECT_ROOT)

        # Tool filtering configuration
        self.use_tool_filtering = TOOL_FILTER_AVAILABLE
        self.persona = "developer"  # Default persona, can be changed per session

        # Context injection configuration
        self.use_context_injection = CONTEXT_INJECTOR_AVAILABLE
        self.context_injector: Optional[Any] = None  # Lazy init
        self.default_project = "automation-analytics-backend"

        # Conversation history tracking
        # Key: conversation_id (e.g., "channel_id:user_id" or "thread_ts")
        # Value: list of message dicts [{"role": "user/assistant", "content": "..."}]
        self._conversations: dict[str, list[dict[str, str]]] = {}
        self._max_history: int = 10  # Keep last N message pairs per conversation
        self._history_ttl: int = 3600  # Clear conversations older than 1 hour
        self._max_conversations: int = 200  # Prevent unbounded memory growth
        self._conversation_timestamps: dict[str, float] = {}

    def _get_conversation_history(self, conversation_id: str) -> list[dict[str, str]]:
        """Get conversation history for a given ID, clearing stale entries."""
        now = time.time()

        # Clear stale conversations
        stale_ids = [
            cid
            for cid, ts in self._conversation_timestamps.items()
            if now - ts > self._history_ttl
        ]
        for cid in stale_ids:
            self._conversations.pop(cid, None)
            self._conversation_timestamps.pop(cid, None)

        # Enforce max conversations limit - remove oldest if over limit
        if len(self._conversations) > self._max_conversations:
            sorted_convs = sorted(
                self._conversation_timestamps.items(), key=lambda x: x[1]
            )
            for cid, _ in sorted_convs[
                : len(self._conversations) - self._max_conversations
            ]:
                self._conversations.pop(cid, None)
                self._conversation_timestamps.pop(cid, None)

        return self._conversations.get(conversation_id, [])

    def _save_conversation_history(
        self, conversation_id: str, user_msg: str, assistant_msg: str
    ) -> None:
        """Save a message exchange to conversation history."""
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = []

        history = self._conversations[conversation_id]
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": assistant_msg})

        # Trim to max history (keep last N pairs = 2N messages)
        max_messages = self._max_history * 2
        if len(history) > max_messages:
            self._conversations[conversation_id] = history[-max_messages:]

        self._conversation_timestamps[conversation_id] = time.time()

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
  → skill_run("test_mr_ephemeral", {"mr_id": 123}) or {"issue_key": "AAP-12345"}
- "start work on AAP-12345"
  → skill_run("start_work", {"issue_key": "AAP-12345"})
- "review MR 123", "review AAP-12345"
  → skill_run("review_pr", {"mr_id": 123}) or {"issue_key": "AAP-12345"}
- "investigate this alert", "look into this alert"
  → skill_run("investigate_slack_alert", {"channel_id": "...", "message_ts": "...", "message_text": "..."})

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

    def _build_context_message(
        self,
        message: str,
        context: Optional[dict],
        resolved_ctx,
        filter_context: Optional[dict] = None,
    ) -> str:
        """Build context-enriched message with memory, patterns, and semantic knowledge."""
        context_parts = []
        if context:
            context_parts.append(
                f"User: {context.get('user_name', 'unknown')} in #{context.get('channel_name', 'unknown')}"
            )

            user_category = context.get("user_category", "unknown")
            include_emojis = context.get("include_emojis", True)

            if user_category == "concerned":
                context_parts.append(
                    "TONE: formal - this is a manager/stakeholder. "
                    "be professional, clear, no typos, no casual slang. skip emojis."
                )
            elif user_category == "safe":
                context_parts.append(
                    "TONE: casual - teammate, full irish dev mode, typos ok, emojis ok"
                )
            else:
                emoji_note = "emojis ok" if include_emojis else "skip emojis"
                context_parts.append(
                    f"TONE: professional - clear and helpful, {emoji_note}"
                )

        if resolved_ctx and resolved_ctx.is_valid():
            if resolved_ctx.repo_path:
                context_parts.append(
                    f"Repository: {resolved_ctx.repo_name} at {resolved_ctx.repo_path}"
                )
            if resolved_ctx.gitlab_project:
                context_parts.append(f"GitLab: {resolved_ctx.gitlab_project}")
            if resolved_ctx.issue_key:
                context_parts.append(f"Jira: {resolved_ctx.issue_key}")
            if resolved_ctx.mr_id:
                context_parts.append(f"MR: !{resolved_ctx.mr_id}")
        elif resolved_ctx and resolved_ctx.needs_clarification():
            repos = ", ".join(a["name"] for a in resolved_ctx.alternatives)
            context_parts.append(
                f"Ambiguous repo - matches: {repos}. Ask user which one."
            )

        # === Add enriched context from HybridToolFilter ===
        enrichment_parts = []
        if filter_context:
            ctx = filter_context.get("context", {})

            # Memory state (active issues, current repo)
            mem = ctx.get("memory_state", {})
            if mem.get("current_repo"):
                enrichment_parts.append(f"Active repo: {mem['current_repo']}")
            if mem.get("current_branch"):
                enrichment_parts.append(f"Branch: {mem['current_branch']}")
            active_issues = mem.get("active_issues", [])
            if active_issues:
                issue_keys = [i.get("key", str(i)) for i in active_issues[:3]]
                enrichment_parts.append(f"Active issues: {', '.join(issue_keys)}")

            # Detected skill
            skill = ctx.get("skill", {})
            if skill.get("name"):
                enrichment_parts.append(f"Detected skill: {skill['name']}")
                if skill.get("description"):
                    enrichment_parts.append(
                        f"Skill purpose: {skill['description'][:100]}"
                    )

            # Learned patterns (error fixes)
            patterns = ctx.get("learned_patterns", [])
            if patterns:
                pattern_hints = []
                for p in patterns[:2]:
                    if p.get("pattern") and p.get("fix"):
                        pattern_hints.append(f"• {p['pattern'][:50]} → {p['fix'][:50]}")
                if pattern_hints:
                    enrichment_parts.append("Known fixes:\n" + "\n".join(pattern_hints))

            # Semantic knowledge (relevant code)
            semantic = ctx.get("semantic_knowledge", [])
            if semantic:
                code_hints = []
                for s in semantic[:2]:
                    if s.get("file"):
                        code_hints.append(
                            f"• {s['file']}: {s.get('content', '')[:80]}..."
                        )
                if code_hints:
                    enrichment_parts.append("Relevant code:\n" + "\n".join(code_hints))

        # Build final message
        result_parts = []
        if context_parts:
            result_parts.append("Context: " + " | ".join(context_parts))
        if enrichment_parts:
            result_parts.append("Enriched Context:\n" + "\n".join(enrichment_parts))
        result_parts.append(f"Message: {message}")

        return "\n\n".join(result_parts)

    async def _execute_tool_loop(self, response, messages, tools):
        """Execute tool calls in a loop until Claude stops requesting tools."""
        while response.stop_reason == "tool_use":
            tool_calls = [
                block for block in response.content if block.type == "tool_use"
            ]

            tool_results = []
            for tc in tool_calls:
                result = await self.tool_executor.execute(tc.name, tc.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result,
                    }
                )

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                tools=tools,
                messages=messages,
            )
        return response

    async def process_message(
        self,
        message: str,
        context: Optional[dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
    ) -> str:
        """
        Process a message using Claude.

        This method:
        1. Gathers context from multiple knowledge sources (Slack, code, Jira, memory)
        2. Builds an enriched system prompt with the gathered context
        3. Calls Claude with the enriched prompt and available tools
        4. Executes any tool calls Claude requests
        5. Returns the final response
        """
        # Load conversation history
        history = []
        if conversation_id:
            history = self._get_conversation_history(conversation_id)

        # Extract repository context
        resolved_ctx = None
        if RESOLVER_AVAILABLE:
            try:
                resolver = ContextResolver()
                resolved_ctx = resolver.from_message(message)
            except Exception as e:
                logger.warning(f"Failed to resolve context: {e}")

        # ============================================================
        # CONTEXT INJECTION - Gather knowledge from multiple sources
        # ============================================================
        gathered_context: Optional[Any] = None  # Type is GatheredContext when available
        if self.use_context_injection and CONTEXT_INJECTOR_AVAILABLE:
            try:
                # Lazy init context injector
                if self.context_injector is None:
                    self.context_injector = ContextInjector(
                        project=self.default_project
                    )

                # Gather context from all sources
                gathered_context = await self.context_injector.gather_context_async(
                    query=message,
                    include_slack=True,  # Always search Slack conversations
                    include_code=True,  # Always search codebase
                    include_jira=True,  # Look up any detected Jira keys
                    include_memory=True,  # Check current work context
                )

                if gathered_context.has_context():
                    logger.info(
                        f"Context injection: {gathered_context.total_results} results "
                        f"from {len([s for s in gathered_context.sources if s.found])} sources "
                        f"in {gathered_context.total_latency_ms:.0f}ms"
                    )
            except Exception as e:
                logger.warning(f"Context injection failed: {e}")
                gathered_context = None

        # Get available tools (with optional NPU-powered filtering)
        all_tools = self.tool_registry.list_tools()
        filter_result = None

        if self.use_tool_filtering and TOOL_FILTER_AVAILABLE:
            # Detect skill early for better filtering
            detected_skill = detect_skill(message) if detect_skill else None

            # Get filtered tool names using 4-layer filter
            # This also returns enriched context (memory, patterns, semantic knowledge)
            filter_result = filter_tools_detailed(
                message=message,
                persona=self.persona,
                detected_skill=detected_skill,
            )

            relevant_tool_names = set(filter_result["tools"])

            # Filter tool definitions to only include relevant tools
            tools = [tool for tool in all_tools if tool["name"] in relevant_tool_names]

            # Check if persona was auto-detected and update
            if filter_result.get("persona_auto_detected"):
                logger.info(
                    f"Auto-detected persona: {filter_result['persona']} "
                    f"(was {self.persona}) via {filter_result['persona_detection_reason']}"
                )

            logger.info(
                f"Tool filtering: {len(all_tools)} → {len(tools)} tools "
                f"({filter_result['reduction_pct']}% reduction, {filter_result['latency_ms']}ms) "
                f"via {', '.join(filter_result['methods'])}"
            )
        else:
            tools = all_tools

        # Build context-enriched message (includes memory, patterns, semantic knowledge)
        enriched_message = self._build_context_message(
            message, context, resolved_ctx, filter_result
        )
        messages = history + [{"role": "user", "content": enriched_message}]

        # ============================================================
        # BUILD SYSTEM PROMPT WITH INJECTED CONTEXT
        # ============================================================
        system_prompt = self.system_prompt
        if gathered_context and gathered_context.has_context():
            # Inject gathered context into system prompt
            system_prompt = self._inject_context_into_prompt(
                base_prompt=self.system_prompt,
                gathered_context=gathered_context,
            )

        # Call Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        # Execute tool calls in a loop
        response = await self._execute_tool_loop(response, messages, tools)

        # Extract final text response
        final_response = ""
        for block in response.content:
            if hasattr(block, "text"):
                final_response += block.text

        result = final_response or "I processed your request but have no response."

        # Save to conversation history if we have an ID
        if conversation_id:
            self._save_conversation_history(conversation_id, message, result)

        return result

    def _inject_context_into_prompt(
        self,
        base_prompt: str,
        gathered_context: Any,  # GatheredContext
    ) -> str:
        """
        Inject gathered context into the system prompt.

        The context is added as a separate section that Claude can reference
        when formulating responses.
        """
        if not gathered_context or not gathered_context.formatted:
            return base_prompt

        # Add context injection instructions
        context_instructions = """

KNOWLEDGE CONTEXT:
The following context has been gathered from past Slack conversations, the codebase,
Jira issues, and memory. Use this information to provide informed, accurate responses.
Reference specific sources when relevant (e.g., "based on the Slack conversation..." or
"looking at the code in..."). If the context doesn't contain relevant information for
the question, you can still use your tools to look up additional details.

"""

        return base_prompt + context_instructions + gathered_context.formatted


# Convenience function
async def ask_claude(message: str, context: Optional[dict[str, Any]] = None) -> str:
    """Quick way to ask Claude something."""
    agent = ClaudeAgent()
    return await agent.process_message(message, context)


__all__ = [
    "ANTHROPIC_AVAILABLE",
    "ClaudeAgent",
    "ToolCall",
    "ToolDefinition",
    "ToolExecutor",
    "ToolRegistry",
    "ToolResult",
    "ask_claude",
]

if __name__ == "__main__":

    async def test():
        agent = ClaudeAgent()

        # Test with a simple query
        response = await agent.process_message(
            "What's the status of AAP-12345?",
            context={"user_name": "testuser", "channel_name": "test"},
        )
        print(response)

    asyncio.run(test())
