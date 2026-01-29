"""
Session Builder - Super Prompt Context Assembly

This module assembles "super prompts" by combining context from multiple sources:
- Personas (tool context, system prompts)
- Skills (workflow definitions)
- Memory (current work, patterns, session history)
- Jira (issue details)
- Slack (message history via search)
- Code (semantic search results)
- Meetings (transcript excerpts)

The assembled context can be:
1. Previewed with token estimates
2. Injected into Cursor's chat database
3. Exported as a prompt template
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

# Workspace paths
WORKSPACE_ROOT = Path.home() / "src" / "redhat-ai-workflow"
PERSONAS_DIR = WORKSPACE_ROOT / "personas"
SKILLS_DIR = WORKSPACE_ROOT / "skills"
MEMORY_DIR = WORKSPACE_ROOT / "memory"
CONFIG_FILE = WORKSPACE_ROOT / "config.json"


def estimate_tokens(text: str) -> int:
    """
    Rough token estimation (4 chars per token average).
    For accurate counts, use tiktoken or similar.
    """
    return len(text) // 4


class SessionBuilder:
    """Builds super prompts from multiple context sources."""

    def __init__(self):
        self.context_sections: dict[str, str] = {}
        self.token_counts: dict[str, int] = {}
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load the main config.json."""
        if CONFIG_FILE.exists():
            try:
                return json.loads(CONFIG_FILE.read_text())
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def add_persona(self, persona_id: str) -> bool:
        """
        Add persona context (system prompt, tool descriptions).

        Args:
            persona_id: The persona identifier (e.g., "developer", "devops")

        Returns:
            True if successful
        """
        persona_file = PERSONAS_DIR / f"{persona_id}.yaml"
        if not persona_file.exists():
            return False

        try:
            persona = yaml.safe_load(persona_file.read_text())

            # Build persona context
            context = f"## Persona: {persona.get('name', persona_id)}\n\n"

            if persona.get("description"):
                context += f"{persona['description']}\n\n"

            if persona.get("system_prompt"):
                context += f"### System Prompt\n{persona['system_prompt']}\n\n"

            if persona.get("tools"):
                context += "### Available Tools\n"
                for tool in persona["tools"]:
                    context += f"- {tool}\n"
                context += "\n"

            self.context_sections["persona"] = context
            self.token_counts["persona"] = estimate_tokens(context)
            return True
        except (yaml.YAMLError, IOError):
            return False

    def add_skill(self, skill_id: str) -> bool:
        """
        Add skill context (workflow definition).

        Args:
            skill_id: The skill identifier (e.g., "start_work", "create_mr")

        Returns:
            True if successful
        """
        # Handle subdirectory skills (e.g., "performance/collect_daily")
        skill_file = SKILLS_DIR / f"{skill_id}.yaml"
        if not skill_file.exists():
            return False

        try:
            skill = yaml.safe_load(skill_file.read_text())

            context = f"## Skill: {skill.get('name', skill_id)}\n\n"

            if skill.get("description"):
                context += f"{skill['description']}\n\n"

            if skill.get("inputs"):
                context += "### Inputs\n"
                for inp in skill["inputs"]:
                    req = " (required)" if inp.get("required") else ""
                    context += f"- **{inp['name']}**{req}: {inp.get('description', '')}\n"
                context += "\n"

            if skill.get("steps"):
                context += "### Steps\n"
                for i, step in enumerate(skill["steps"], 1):
                    context += f"{i}. {step.get('name', 'Step')}"
                    if step.get("tool"):
                        context += f" (tool: {step['tool']})"
                    context += "\n"
                context += "\n"

            # Add to existing skills or create new section
            if "skills" not in self.context_sections:
                self.context_sections["skills"] = ""
                self.token_counts["skills"] = 0

            self.context_sections["skills"] += context
            self.token_counts["skills"] += estimate_tokens(context)
            return True
        except (yaml.YAMLError, IOError):
            return False

    def add_memory(self, memory_path: str) -> bool:
        """
        Add memory context from a specific path.

        Args:
            memory_path: Relative path within memory/ (e.g., "state/current_work")

        Returns:
            True if successful
        """
        # Try both .yaml and .json extensions
        for ext in [".yaml", ".json"]:
            full_path = MEMORY_DIR / f"{memory_path}{ext}"
            if full_path.exists():
                try:
                    content = full_path.read_text()

                    # Parse and format
                    if ext == ".yaml":
                        data = yaml.safe_load(content)
                    else:
                        data = json.loads(content)

                    context = f"## Memory: {memory_path}\n\n"
                    context += f"```yaml\n{yaml.dump(data, default_flow_style=False)}\n```\n\n"

                    # Add to existing memory or create new section
                    if "memory" not in self.context_sections:
                        self.context_sections["memory"] = ""
                        self.token_counts["memory"] = 0

                    self.context_sections["memory"] += context
                    self.token_counts["memory"] += estimate_tokens(context)
                    return True
                except (yaml.YAMLError, json.JSONDecodeError, IOError):
                    pass

        return False

    def add_jira_issue(self, issue_key: str, issue_data: Optional[dict] = None) -> bool:
        """
        Add Jira issue context.

        Args:
            issue_key: The Jira issue key (e.g., "AAP-12345")
            issue_data: Optional pre-fetched issue data

        Returns:
            True if successful
        """
        if issue_data is None:
            # Would need to fetch from Jira API
            # For now, just add a placeholder
            context = f"## Jira Issue: {issue_key}\n\n"
            context += "*Issue details will be fetched from Jira*\n\n"
        else:
            context = f"## Jira Issue: {issue_key}\n\n"
            context += f"**Summary:** {issue_data.get('summary', 'N/A')}\n\n"

            if issue_data.get("description"):
                context += f"**Description:**\n{issue_data['description']}\n\n"

            if issue_data.get("status"):
                context += f"**Status:** {issue_data['status']}\n"

            if issue_data.get("priority"):
                context += f"**Priority:** {issue_data['priority']}\n"

            if issue_data.get("assignee"):
                context += f"**Assignee:** {issue_data['assignee']}\n"

            context += "\n"

        self.context_sections["jira"] = context
        self.token_counts["jira"] = estimate_tokens(context)
        return True

    def add_slack_results(self, query: str, results: list[dict]) -> bool:
        """
        Add Slack search results.

        Args:
            query: The search query used
            results: List of message results from slack_search_messages

        Returns:
            True if successful
        """
        context = f'## Slack Messages: "{query}"\n\n'

        if not results:
            context += "*No matching messages found*\n\n"
        else:
            for msg in results[:10]:  # Limit to 10 messages
                context += f"**{msg.get('user', 'Unknown')}** in #{msg.get('channel', 'unknown')} "
                context += f"({msg.get('timestamp', 'unknown time')}):\n"
                context += f"> {msg.get('text', '')}\n\n"

        self.context_sections["slack"] = context
        self.token_counts["slack"] = estimate_tokens(context)
        return True

    def add_code_results(self, query: str, results: list[dict]) -> bool:
        """
        Add code search results.

        Args:
            query: The search query used
            results: List of code results from code_search

        Returns:
            True if successful
        """
        context = f'## Code Search: "{query}"\n\n'

        if not results:
            context += "*No matching code found*\n\n"
        else:
            for result in results[:5]:  # Limit to 5 results
                context += f"### {result.get('file', 'Unknown file')}"
                if result.get("line"):
                    context += f" (line {result['line']})"
                context += "\n\n"

                if result.get("snippet"):
                    context += f"```\n{result['snippet']}\n```\n\n"

                if result.get("relevance"):
                    context += f"*Relevance: {result['relevance']:.2f}*\n\n"

        self.context_sections["code"] = context
        self.token_counts["code"] = estimate_tokens(context)
        return True

    def add_meeting_context(self, meeting_id: str, excerpts: list[str]) -> bool:
        """
        Add meeting transcript excerpts.

        Args:
            meeting_id: The meeting identifier
            excerpts: List of relevant transcript excerpts

        Returns:
            True if successful
        """
        context = f"## Meeting: {meeting_id}\n\n"

        for excerpt in excerpts:
            context += f"> {excerpt}\n\n"

        self.context_sections["meeting"] = context
        self.token_counts["meeting"] = estimate_tokens(context)
        return True

    def add_custom_context(self, title: str, content: str) -> bool:
        """
        Add custom context section.

        Args:
            title: Section title
            content: Section content

        Returns:
            True if successful
        """
        context = f"## {title}\n\n{content}\n\n"

        key = title.lower().replace(" ", "_")
        self.context_sections[key] = context
        self.token_counts[key] = estimate_tokens(context)
        return True

    def build(self) -> str:
        """
        Build the final super prompt from all context sections.

        Returns:
            The assembled prompt string
        """
        # Order sections logically
        section_order = [
            "persona",
            "jira",
            "memory",
            "skills",
            "slack",
            "code",
            "meeting",
        ]

        prompt = "# Session Context\n\n"
        prompt += f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n"
        prompt += "---\n\n"

        # Add ordered sections
        for section in section_order:
            if section in self.context_sections:
                prompt += self.context_sections[section]

        # Add any remaining sections
        for section, content in self.context_sections.items():
            if section not in section_order:
                prompt += content

        return prompt

    def get_token_summary(self) -> dict:
        """
        Get a summary of token counts by section.

        Returns:
            Dict with section names and token counts
        """
        total = sum(self.token_counts.values())
        return {
            "sections": self.token_counts.copy(),
            "total": total,
            "warning": total > 50000,
            "danger": total > 100000,
        }

    def preview(self) -> dict:
        """
        Get a preview of the assembled prompt.

        Returns:
            Dict with prompt preview and token info
        """
        prompt = self.build()
        tokens = self.get_token_summary()

        return {
            "prompt": prompt,
            "tokens": tokens,
            "sections": list(self.context_sections.keys()),
        }

    def export_template(self, name: str, description: str = "") -> dict:
        """
        Export the current configuration as a reusable template.

        Args:
            name: Template name
            description: Template description

        Returns:
            Template configuration dict
        """
        return {
            "name": name,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "sections": list(self.context_sections.keys()),
            "token_estimate": sum(self.token_counts.values()),
        }


def build_auto_context(issue_key: str) -> SessionBuilder:
    """
    Build context automatically based on an issue key.

    This function:
    1. Fetches the Jira issue
    2. Searches Slack for related messages
    3. Searches code for related files
    4. Loads relevant memory

    Args:
        issue_key: The Jira issue key

    Returns:
        A SessionBuilder with auto-populated context
    """
    builder = SessionBuilder()

    # Add Jira issue (placeholder for now)
    builder.add_jira_issue(issue_key)

    # Add default memory sections
    builder.add_memory("state/current_work")
    builder.add_memory("learned/patterns")

    # Slack and code search would need async calls to the tools
    # For now, add placeholders
    builder.add_slack_results(issue_key, [])
    builder.add_code_results(issue_key, [])

    return builder


# CLI interface for testing
if __name__ == "__main__":
    builder = SessionBuilder()

    # Example usage
    builder.add_persona("developer")
    builder.add_skill("start_work")
    builder.add_memory("state/current_work")
    builder.add_jira_issue("AAP-12345")

    preview = builder.preview()

    print("=== Token Summary ===")
    print(json.dumps(preview["tokens"], indent=2))
    print()
    print("=== Prompt Preview ===")
    print(preview["prompt"][:2000] + "..." if len(preview["prompt"]) > 2000 else preview["prompt"])
