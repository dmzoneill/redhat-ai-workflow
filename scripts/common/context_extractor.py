"""
Context Extractor for Slack @me Commands.

Extracts conversation context from Slack threads and channels to provide
context for commands like create_jira_issue that need to understand
what the user is talking about.

Context includes:
- Conversation summary (Claude-generated)
- Mentioned Jira issues (AAP-XXXXX patterns)
- Mentioned users (@mentions)
- URLs (GitLab MRs, Jira links, etc.)
- Key topics/entities extracted
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Project root for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent


@dataclass
class ConversationContext:
    """Extracted context from a Slack conversation."""

    # Source information
    channel_id: str = ""
    thread_ts: str | None = None
    message_count: int = 0

    # Extracted entities
    jira_issues: list[str] = field(default_factory=list)
    gitlab_mrs: list[dict[str, str]] = field(default_factory=list)
    gitlab_issues: list[dict[str, str]] = field(default_factory=list)
    mentioned_users: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)

    # Conversation content
    messages: list[dict[str, str]] = field(default_factory=list)
    raw_text: str = ""

    # Claude-generated summary
    summary: str = ""
    inferred_type: str = ""  # bug, feature, task, question
    inferred_priority: str = ""  # high, medium, low
    key_topics: list[str] = field(default_factory=list)

    # Confidence in extraction
    confidence: str = "low"  # low, medium, high

    def is_valid(self) -> bool:
        """Check if we have meaningful context."""
        return bool(self.messages or self.jira_issues or self.summary)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for skill inputs."""
        return {
            "channel_id": self.channel_id,
            "thread_ts": self.thread_ts,
            "message_count": self.message_count,
            "jira_issues": self.jira_issues,
            "gitlab_mrs": self.gitlab_mrs,
            "mentioned_users": self.mentioned_users,
            "urls": self.urls,
            "summary": self.summary,
            "inferred_type": self.inferred_type,
            "inferred_priority": self.inferred_priority,
            "key_topics": self.key_topics,
            "raw_text": self.raw_text[:2000] if self.raw_text else "",
        }

    def to_skill_inputs(self, skill_name: str) -> dict[str, Any]:
        """
        Convert context to inputs for a specific skill.

        Args:
            skill_name: Name of the skill to generate inputs for

        Returns:
            Dictionary of skill inputs
        """
        inputs: dict[str, Any] = {}

        if skill_name == "create_jira_issue":
            inputs["summary"] = self.summary or "Issue from Slack conversation"
            inputs["description"] = self._build_jira_description()

            if self.inferred_type:
                type_map = {
                    "bug": "Bug",
                    "feature": "Story",
                    "task": "Task",
                    "question": "Task",
                }
                inputs["issue_type"] = type_map.get(self.inferred_type.lower(), "Task")

            if self.inferred_priority:
                priority_map = {
                    "high": "High",
                    "medium": "Medium",
                    "low": "Low",
                    "critical": "Highest",
                }
                inputs["priority"] = priority_map.get(self.inferred_priority.lower(), "Medium")

            if self.jira_issues:
                inputs["link_to"] = self.jira_issues[0]

            inputs["slack_format"] = True

        elif skill_name == "investigate_alert":
            inputs["context"] = self.raw_text
            inputs["summary"] = self.summary

        elif skill_name in ("start_work", "review_pr"):
            if self.jira_issues:
                inputs["issue_key"] = self.jira_issues[0]
            if self.gitlab_mrs:
                inputs["mr_id"] = self.gitlab_mrs[0].get("id")
                inputs["project"] = self.gitlab_mrs[0].get("project")

        return inputs

    def _build_jira_description(self) -> str:
        """Build a Jira description from context."""
        parts = []

        if self.summary:
            parts.append(f"## Summary\n\n{self.summary}")

        if self.key_topics:
            parts.append("## Topics\n\n" + ", ".join(self.key_topics))

        if self.jira_issues:
            parts.append("## Related Issues\n\n" + ", ".join(self.jira_issues))

        if self.urls:
            parts.append("## References\n\n" + "\n".join(f"- {url}" for url in self.urls[:5]))

        parts.append(f"\n---\n_Created from Slack conversation in {self.channel_id}_")

        return "\n\n".join(parts)


class ContextExtractor:
    """
    Extracts context from Slack threads and channels.

    Uses the Slack client to fetch message history and Claude to
    summarize and extract meaningful context.
    """

    # Regex patterns for entity extraction
    JIRA_PATTERN = re.compile(r"\b([A-Z]{2,10}-\d+)\b")
    GITLAB_MR_PATTERN = re.compile(r"https?://[^/]+/([^/]+/[^/]+)/-/merge_requests/(\d+)")
    GITLAB_ISSUE_PATTERN = re.compile(r"https?://[^/]+/([^/]+/[^/]+)/-/issues/(\d+)")
    URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")
    SLACK_USER_PATTERN = re.compile(r"<@([A-Z0-9]+)>")

    def __init__(
        self,
        slack_client: Any | None = None,
        claude_agent: Any | None = None,
        context_messages_limit: int = 20,
    ):
        """
        Initialize the context extractor.

        Args:
            slack_client: Slack client for fetching messages
            claude_agent: Claude agent for summarization
            context_messages_limit: Max messages to fetch for context
        """
        self._slack_client = slack_client
        self._claude_agent = claude_agent
        self._limit = context_messages_limit

    async def extract(
        self,
        channel_id: str,
        thread_ts: str | None = None,
        message_ts: str | None = None,
        exclude_command_message: bool = True,
    ) -> ConversationContext:
        """
        Extract context from a Slack conversation.

        Strategy:
        1. If thread_ts provided, fetch thread replies
        2. Otherwise, fetch recent channel messages
        3. Extract entities (Jira issues, URLs, etc.)
        4. Optionally summarize with Claude

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp (if in a thread)
            message_ts: Message timestamp of the command
            exclude_command_message: Whether to exclude the @me message itself

        Returns:
            ConversationContext with extracted data
        """
        context = ConversationContext(
            channel_id=channel_id,
            thread_ts=thread_ts,
        )

        # Fetch messages
        messages = await self._fetch_messages(channel_id, thread_ts)

        if not messages:
            logger.warning(f"No messages found for context in {channel_id}")
            return context

        # Optionally exclude the command message itself
        if exclude_command_message and message_ts:
            messages = [m for m in messages if m.get("ts") != message_ts]

        context.message_count = len(messages)

        # Build structured message list
        for msg in messages:
            context.messages.append(
                {
                    "user": msg.get("user", "unknown"),
                    "text": msg.get("text", ""),
                    "ts": msg.get("ts", ""),
                }
            )

        # Build raw text for analysis
        context.raw_text = self._build_raw_text(messages)

        # Extract entities
        self._extract_entities(context)

        # Summarize with Claude if available
        if self._claude_agent and messages:
            await self._summarize_with_claude(context)

        # Set confidence based on what we extracted
        context.confidence = self._assess_confidence(context)

        return context

    async def _fetch_messages(self, channel_id: str, thread_ts: str | None) -> list[dict[str, Any]]:
        """Fetch messages from Slack."""
        if not self._slack_client:
            logger.warning("No Slack client available for context extraction")
            return []

        try:
            if thread_ts:
                # Fetch thread replies
                messages = await self._slack_client.get_thread_replies(
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    limit=self._limit,
                )
            else:
                # Fetch recent channel messages
                messages = await self._slack_client.get_channel_history(
                    channel_id=channel_id,
                    limit=self._limit,
                )

            return messages or []

        except Exception as e:
            logger.error(f"Failed to fetch messages: {e}")
            return []

    def _build_raw_text(self, messages: list[dict[str, Any]]) -> str:
        """Build raw text from messages for analysis."""
        lines = []
        for msg in messages:
            user = msg.get("user", "unknown")
            text = msg.get("text", "")
            if text:
                lines.append(f"{user}: {text}")
        return "\n".join(lines)

    def _extract_entities(self, context: ConversationContext) -> None:
        """Extract entities from the raw text."""
        text = context.raw_text

        # Extract Jira issues
        jira_matches = self.JIRA_PATTERN.findall(text)
        context.jira_issues = list(dict.fromkeys(jira_matches))  # Dedupe, preserve order

        # Extract GitLab MRs
        for match in self.GITLAB_MR_PATTERN.finditer(text):
            context.gitlab_mrs.append(
                {
                    "project": match.group(1),
                    "id": match.group(2),
                    "url": match.group(0),
                }
            )

        # Extract GitLab issues
        for match in self.GITLAB_ISSUE_PATTERN.finditer(text):
            context.gitlab_issues.append(
                {
                    "project": match.group(1),
                    "id": match.group(2),
                    "url": match.group(0),
                }
            )

        # Extract URLs (excluding already matched GitLab URLs)
        gitlab_urls = {mr["url"] for mr in context.gitlab_mrs}
        gitlab_urls.update(issue["url"] for issue in context.gitlab_issues)

        for match in self.URL_PATTERN.finditer(text):
            url = match.group(0).rstrip(".,;:)")
            if url not in gitlab_urls:
                context.urls.append(url)
        context.urls = list(dict.fromkeys(context.urls))  # Dedupe

        # Extract mentioned users
        user_matches = self.SLACK_USER_PATTERN.findall(text)
        context.mentioned_users = list(dict.fromkeys(user_matches))

    async def _summarize_with_claude(self, context: ConversationContext) -> None:
        """Use Claude to summarize the conversation and infer details."""
        if not self._claude_agent:
            return

        prompt = f"""Analyze this Slack conversation and extract:
1. A brief summary (1-2 sentences) suitable as a Jira issue title
2. The type of issue being discussed: bug, feature, task, or question
3. The priority: critical, high, medium, or low
4. 2-3 key topics or components mentioned

Conversation:
{context.raw_text[:3000]}

Respond in this exact JSON format:
{{
    "summary": "Brief summary here",
    "type": "bug|feature|task|question",
    "priority": "critical|high|medium|low",
    "topics": ["topic1", "topic2"]
}}
"""

        try:
            response = await self._claude_agent.process_message(
                prompt,
                context={"purpose": "context_extraction"},
            )

            # Parse JSON response
            # Try to extract JSON from the response
            json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                context.summary = data.get("summary", "")
                context.inferred_type = data.get("type", "")
                context.inferred_priority = data.get("priority", "")
                context.key_topics = data.get("topics", [])

        except Exception as e:
            logger.warning(f"Failed to summarize with Claude: {e}")
            # Fall back to simple extraction
            context.summary = self._simple_summary(context.raw_text)

    def _simple_summary(self, text: str) -> str:
        """Create a simple summary without Claude."""
        # Take first non-empty line as summary
        for line in text.split("\n"):
            # Skip user prefix
            if ": " in line:
                content = line.split(": ", 1)[1]
                if len(content) > 10:
                    return content[:100] + ("..." if len(content) > 100 else "")
        return "Issue from Slack conversation"

    def _assess_confidence(self, context: ConversationContext) -> str:
        """Assess confidence level of extracted context."""
        score = 0

        if context.summary:
            score += 2
        if context.jira_issues:
            score += 2
        if context.message_count >= 3:
            score += 1
        if context.inferred_type:
            score += 1
        if context.key_topics:
            score += 1

        if score >= 5:
            return "high"
        elif score >= 3:
            return "medium"
        return "low"

    def extract_from_text(self, text: str) -> ConversationContext:
        """
        Extract context from raw text (synchronous, no Slack fetch).

        Useful for testing or when messages are already available.

        Args:
            text: Raw conversation text

        Returns:
            ConversationContext with extracted entities
        """
        context = ConversationContext(raw_text=text)
        self._extract_entities(context)
        context.summary = self._simple_summary(text)
        context.confidence = self._assess_confidence(context)
        return context


async def extract_context(
    channel_id: str,
    thread_ts: str | None = None,
    message_ts: str | None = None,
    slack_client: Any | None = None,
    claude_agent: Any | None = None,
) -> ConversationContext:
    """
    Convenience function to extract context.

    Args:
        channel_id: Slack channel ID
        thread_ts: Thread timestamp (if in thread)
        message_ts: Message timestamp of command
        slack_client: Slack client instance
        claude_agent: Claude agent for summarization

    Returns:
        ConversationContext with extracted data
    """
    extractor = ContextExtractor(
        slack_client=slack_client,
        claude_agent=claude_agent,
    )
    return await extractor.extract(channel_id, thread_ts, message_ts)
