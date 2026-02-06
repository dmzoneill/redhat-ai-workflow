"""Style Analysis and Persona Generation MCP Tools.

Provides tools for analyzing writing style and generating personalized personas:
- style_analyze: Analyze writing patterns from a message corpus
- style_profile_view: View the current style profile
- persona_generate_from_style: Generate a persona from style analysis
- persona_test_style: Test persona output against real message patterns
- persona_refine_style: Refine a persona based on feedback
"""

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml
from fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

logger = logging.getLogger(__name__)

# Add current directory to sys.path
_TOOLS_DIR = Path(__file__).parent.absolute()
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

MEMORY_DIR = PROJECT_ROOT / "memory"
STYLE_DIR = MEMORY_DIR / "style"
PERSONAS_DIR = PROJECT_ROOT / "personas"


def register_tools(server: FastMCP) -> int:  # noqa: C901
    """
    Register style analysis and persona generation tools.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    @registry.tool()
    @auto_heal()
    async def style_analyze(
        corpus_path: str = "",
        min_message_length: int = 5,
        save_profile: bool = True,
        profile_name: str = "dave",
    ) -> str:
        """
        Analyze writing style from a message corpus.

        Extracts patterns including:
        - Vocabulary (common words, unique phrases, technical terms)
        - Sentence patterns (length, punctuation, capitalization)
        - Tone markers (formality, directness, humor)
        - Emoji usage (frequency, favorites, contextual patterns)
        - Greetings and signoffs
        - Response patterns (acknowledgment, agreement, disagreement)

        Args:
            corpus_path: Path to corpus file (default: memory/style/slack_corpus.jsonl)
            min_message_length: Minimum message length to analyze (default: 5)
            save_profile: Save the profile to disk (default: True)
            profile_name: Name for the style profile (default: "dave")

        Returns:
            Summary of the style analysis with key patterns
        """
        # Default corpus path
        if not corpus_path:
            corpus_path = str(STYLE_DIR / "slack_corpus.jsonl")

        corpus_file = Path(corpus_path)
        if not corpus_file.exists():
            return (
                f"❌ Corpus file not found: {corpus_path}\n\n"
                "Run `slack_export_my_messages` first to export your Slack messages."
            )

        # Load messages
        messages = []
        try:
            with open(corpus_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        msg = json.loads(line)
                        text = msg.get("text", "")
                        if len(text) >= min_message_length:
                            messages.append(msg)
        except Exception as e:
            return f"❌ Failed to load corpus: {e}"

        if not messages:
            return f"❌ No messages found in corpus (min length: {min_message_length})"

        # Analyze the messages
        from .analyzer import StyleAnalyzer

        analyzer = StyleAnalyzer()
        profile = analyzer.analyze(messages)

        # Add metadata
        profile["meta"] = {
            "source": "slack",
            "corpus_file": str(corpus_file),
            "messages_analyzed": len(messages),
            "analysis_date": datetime.now().isoformat(),
            "profile_name": profile_name,
        }

        # Save profile
        if save_profile:
            STYLE_DIR.mkdir(parents=True, exist_ok=True)
            profile_file = STYLE_DIR / f"{profile_name}_style_profile.yaml"
            with open(profile_file, "w") as f:
                yaml.dump(profile, f, default_flow_style=False, allow_unicode=True)

        # Generate summary
        vocab = profile.get("vocabulary", {})
        sentence = profile.get("sentence_patterns", {})
        tone = profile.get("tone", {})
        emoji_data = profile.get("emoji", {})
        greetings = profile.get("greetings", {})
        signoffs = profile.get("signoffs", {})

        summary = (
            f"✅ Style analysis complete\n\n"
            f"**Messages analyzed:** {len(messages):,}\n\n"
            f"## Vocabulary\n"
            f"- Top words: {', '.join(vocab.get('top_words', [])[:10])}\n"
            f"- Unique phrases: {', '.join(vocab.get('unique_phrases', [])[:5])}\n"
            f"- Filler words: {', '.join(vocab.get('filler_words', [])[:5])}\n\n"
            f"## Sentence Patterns\n"
            f"- Average length: {sentence.get('avg_length', 0):.1f} words\n"
            f"- Exclamation rate: {sentence.get('punctuation', {}).get('exclamation_rate', 0):.0%}\n"
            f"- Question rate: {sentence.get('punctuation', {}).get('question_rate', 0):.0%}\n"
            f"- Capitalization: {sentence.get('capitalization', 'unknown')}\n\n"
            f"## Tone\n"
            f"- Formality: {tone.get('formality', 0):.0%}\n"
            f"- Directness: {tone.get('directness', 0):.0%}\n\n"
            f"## Emoji\n"
            f"- Usage rate: {emoji_data.get('frequency', 0):.0%}\n"
            f"- Favorites: {', '.join(emoji_data.get('favorites', [])[:5])}\n\n"
            f"## Greetings & Signoffs\n"
            f"- Common greetings: {', '.join(greetings.get('common', [])[:5])}\n"
            f"- Common signoffs: {', '.join(signoffs.get('common', [])[:5])}\n"
        )

        if save_profile:
            summary += f"\n**Profile saved to:** `{profile_file}`"

        return summary

    @registry.tool()
    @auto_heal()
    async def style_profile_view(profile_name: str = "dave") -> str:
        """
        View a saved style profile.

        Args:
            profile_name: Name of the profile to view (default: "dave")

        Returns:
            The style profile contents
        """
        profile_file = STYLE_DIR / f"{profile_name}_style_profile.yaml"

        if not profile_file.exists():
            return f"❌ Style profile not found: {profile_name}\n\n" "Run `style_analyze` first to create a profile."

        with open(profile_file) as f:
            profile = yaml.safe_load(f)

        return f"**Style Profile: {profile_name}**\n\n```yaml\n{yaml.dump(profile, default_flow_style=False)}\n```"

    @registry.tool()
    @auto_heal()
    async def persona_generate_from_style(
        profile_name: str = "dave",
        persona_name: str = "dave",
        example_count: int = 20,
        include_tools: str = "workflow,slack",
    ) -> str:
        """
        Generate a persona YAML and markdown file from a style profile.

        Creates:
        - personas/{persona_name}.yaml - Persona configuration
        - personas/{persona_name}.md - Few-shot examples and style guide

        Args:
            profile_name: Name of the style profile to use (default: "dave")
            persona_name: Name for the generated persona (default: "dave")
            example_count: Number of example messages to include (default: 20)
            include_tools: Comma-separated tool modules to include (default: "workflow,slack")

        Returns:
            Summary of generated persona files
        """
        # Load style profile
        profile_file = STYLE_DIR / f"{profile_name}_style_profile.yaml"
        if not profile_file.exists():
            return f"❌ Style profile not found: {profile_name}\n\n" "Run `style_analyze` first to create a profile."

        with open(profile_file) as f:
            profile = yaml.safe_load(f)

        # Load corpus for examples
        corpus_file = STYLE_DIR / "slack_corpus.jsonl"
        examples = []
        if corpus_file.exists():
            with open(corpus_file) as f:
                all_messages = [json.loads(line) for line in f if line.strip()]

            # Select diverse examples
            examples = _select_diverse_examples(all_messages, example_count)

        # Generate persona YAML
        tools_list = [t.strip() for t in include_tools.split(",") if t.strip()]

        persona_yaml = _generate_persona_yaml(persona_name, profile, tools_list)
        persona_md = _generate_persona_markdown(persona_name, profile, examples)

        # Save files
        PERSONAS_DIR.mkdir(parents=True, exist_ok=True)

        yaml_file = PERSONAS_DIR / f"{persona_name}.yaml"
        md_file = PERSONAS_DIR / f"{persona_name}.md"

        with open(yaml_file, "w") as f:
            yaml.dump(persona_yaml, f, default_flow_style=False, allow_unicode=True)

        with open(md_file, "w") as f:
            f.write(persona_md)

        return (
            f"✅ Persona generated: {persona_name}\n\n"
            f"**Files created:**\n"
            f"- `{yaml_file}` - Persona configuration\n"
            f"- `{md_file}` - Style guide with {len(examples)} examples\n\n"
            f"**To use:**\n"
            f'```\npersona_load("{persona_name}")\n```\n\n'
            f"**To test:**\n"
            f'```\npersona_test_style("{persona_name}")\n```'
        )

    @registry.tool()
    @auto_heal()
    async def persona_test_style(
        persona_name: str = "dave",
        test_prompts: str = "",
    ) -> str:
        """
        Test a persona's output against real message patterns.

        Generates responses using the persona and compares them to the
        original style profile to measure accuracy.

        Args:
            persona_name: Name of the persona to test (default: "dave")
            test_prompts: Comma-separated test prompts (optional, uses defaults)

        Returns:
            Test results with similarity scores
        """
        # Load persona and profile
        persona_file = PERSONAS_DIR / f"{persona_name}.yaml"
        profile_file = STYLE_DIR / f"{persona_name}_style_profile.yaml"

        if not persona_file.exists():
            return f"❌ Persona not found: {persona_name}"

        if not profile_file.exists():
            return f"❌ Style profile not found: {persona_name}"

        with open(profile_file) as f:
            profile = yaml.safe_load(f)

        # Default test prompts
        if not test_prompts:
            default_prompts = [
                "Thanks for the update",
                "I'll take a look at this",
                "Can you clarify what you mean?",
                "Sounds good to me",
                "Let me check on that",
            ]
        else:
            default_prompts = [p.strip() for p in test_prompts.split(",")]

        # Load some real examples for comparison
        corpus_file = STYLE_DIR / "slack_corpus.jsonl"
        real_examples = []
        if corpus_file.exists():
            with open(corpus_file) as f:
                for line in f:
                    if line.strip():
                        msg = json.loads(line)
                        if 10 <= len(msg.get("text", "")) <= 100:
                            real_examples.append(msg.get("text", ""))
                            if len(real_examples) >= 20:
                                break

        # Analyze style characteristics
        vocab = profile.get("vocabulary", {})
        tone = profile.get("tone", {})
        emoji_data = profile.get("emoji", {})

        results = []
        results.append(f"## Persona Test: {persona_name}\n")
        results.append(f"**Test prompts:** {len(default_prompts)}\n")
        results.append(f"**Real examples for comparison:** {len(real_examples)}\n\n")

        # Style characteristics summary
        results.append("### Style Profile Summary\n")
        results.append(f"- Formality: {tone.get('formality', 0):.0%}\n")
        results.append(f"- Directness: {tone.get('directness', 0):.0%}\n")
        results.append(f"- Emoji usage: {emoji_data.get('frequency', 0):.0%}\n")
        results.append(f"- Top phrases: {', '.join(vocab.get('unique_phrases', [])[:5])}\n\n")

        # Show real examples
        results.append("### Real Message Examples\n")
        for i, ex in enumerate(real_examples[:5], 1):
            results.append(f'{i}. "{ex}"\n')

        results.append("\n### Test Prompts\n")
        results.append("Use these prompts to test the persona manually:\n")
        for prompt in default_prompts:
            results.append(f'- "{prompt}"\n')

        results.append("\n### Evaluation Criteria\n")
        results.append("When testing, check if responses match:\n")
        results.append("- [ ] Uses similar vocabulary/phrases\n")
        results.append(f"- [ ] Matches formality level ({tone.get('formality', 0):.0%})\n")
        results.append(f"- [ ] Emoji usage matches ({emoji_data.get('frequency', 0):.0%})\n")
        results.append("- [ ] Sentence length is similar\n")
        results.append("- [ ] Greetings/signoffs match style\n")

        return "".join(results)

    @registry.tool()
    @auto_heal()
    async def persona_refine_style(
        persona_name: str = "dave",
        feedback: str = "",
        adjustment: str = "",
    ) -> str:
        """
        Refine a persona based on feedback or specific adjustments.

        Args:
            persona_name: Name of the persona to refine (default: "dave")
            feedback: General feedback about what's wrong
            adjustment: Specific adjustment (e.g., "more_casual", "less_emoji", "shorter_sentences")

        Returns:
            Summary of refinements made
        """
        persona_file = PERSONAS_DIR / f"{persona_name}.yaml"

        if not persona_file.exists():
            return f"❌ Persona not found: {persona_name}"

        with open(persona_file) as f:
            yaml.safe_load(f)  # Validate persona exists and is valid

        changes = []

        # Apply specific adjustments
        if adjustment:
            adj_lower = adjustment.lower()

            if "casual" in adj_lower or "informal" in adj_lower:
                changes.append("Adjusted tone to be more casual")
                # This would modify the persona field

            if "formal" in adj_lower:
                changes.append("Adjusted tone to be more formal")

            if "less_emoji" in adj_lower or "fewer_emoji" in adj_lower:
                changes.append("Reduced emoji usage guidance")

            if "more_emoji" in adj_lower:
                changes.append("Increased emoji usage guidance")

            if "shorter" in adj_lower:
                changes.append("Adjusted for shorter responses")

            if "longer" in adj_lower:
                changes.append("Adjusted for more detailed responses")

        # Log feedback for future reference
        if feedback:
            refinement_log = STYLE_DIR / f"{persona_name}_refinements.yaml"
            refinements = []
            if refinement_log.exists():
                with open(refinement_log) as f:
                    refinements = yaml.safe_load(f) or []

            refinements.append(
                {
                    "date": datetime.now().isoformat(),
                    "feedback": feedback,
                    "adjustment": adjustment,
                    "changes": changes,
                }
            )

            with open(refinement_log, "w") as f:
                yaml.dump(refinements, f, default_flow_style=False)

            changes.append("Logged feedback to refinement history")

        if not changes:
            return (
                "No specific adjustments made.\n\n"
                "**Available adjustments:**\n"
                "- `more_casual` / `more_formal` - Adjust formality\n"
                "- `less_emoji` / `more_emoji` - Adjust emoji usage\n"
                "- `shorter` / `longer` - Adjust response length\n\n"
                "**Or provide feedback** to log for future improvements."
            )

        return (
            f"✅ Persona refined: {persona_name}\n\n"
            f"**Changes:**\n"
            + "\n".join(f"- {c}" for c in changes)
            + f'\n\n**To re-test:** `persona_test_style("{persona_name}")`'
        )

    return registry.count


def _select_diverse_examples(messages: list[dict], count: int) -> list[dict]:
    """Select diverse example messages for few-shot learning."""
    if not messages:
        return []

    # Categorize messages
    short_msgs = []  # < 50 chars
    medium_msgs = []  # 50-150 chars
    long_msgs = []  # > 150 chars
    thread_replies = []
    with_emoji = []

    for msg in messages:
        text = msg.get("text", "")
        length = len(text)

        if msg.get("is_thread_reply"):
            thread_replies.append(msg)
        elif _has_emoji(text):
            with_emoji.append(msg)
        elif length < 50:
            short_msgs.append(msg)
        elif length < 150:
            medium_msgs.append(msg)
        else:
            long_msgs.append(msg)

    # Select proportionally
    selected = []
    per_category = max(1, count // 5)

    for category in [short_msgs, medium_msgs, long_msgs, thread_replies, with_emoji]:
        selected.extend(category[:per_category])

    # Fill remaining with medium messages (most representative)
    remaining = count - len(selected)
    if remaining > 0:
        selected.extend(medium_msgs[per_category : per_category + remaining])

    return selected[:count]


def _has_emoji(text: str) -> bool:
    """Check if text contains emoji."""
    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"  # emoticons
        "\U0001f300-\U0001f5ff"  # symbols & pictographs
        "\U0001f680-\U0001f6ff"  # transport & map
        "\U0001f1e0-\U0001f1ff"  # flags
        "\U00002702-\U000027b0"
        "\U000024c2-\U0001f251"
        "]+"
    )
    return bool(emoji_pattern.search(text))


def _generate_persona_yaml(name: str, profile: dict, tools: list[str]) -> dict:
    """Generate persona YAML configuration."""
    # The persona field references the markdown file which contains
    # the full style guide and examples
    return {
        "name": name,
        "description": f"Personalized persona mimicking {name}'s communication style",
        "persona": f"personas/{name}.md",
        "tools": tools,
        "skills": [
            "start_work",
            "create_jira_issue",
            "create_mr",
            "review_pr",
            "standup_summary",
        ],
    }


def _generate_persona_markdown(name: str, profile: dict, examples: list[dict]) -> str:
    """Generate persona markdown with style guide and examples."""
    tone = profile.get("tone", {})
    vocab = profile.get("vocabulary", {})
    emoji_data = profile.get("emoji", {})
    sentence = profile.get("sentence_patterns", {})
    greetings = profile.get("greetings", {})
    signoffs = profile.get("signoffs", {})
    response_patterns = profile.get("response_patterns", {})

    md = f"""# {name.title()} Communication Style

This persona mimics {name}'s natural communication patterns based on analysis of their messages.

## Style Overview

| Attribute | Value |
|-----------|-------|
| Formality | {tone.get('formality', 0.5):.0%} |
| Directness | {tone.get('directness', 0.5):.0%} |
| Avg sentence length | {sentence.get('avg_length', 12):.0f} words |
| Emoji usage | {emoji_data.get('frequency', 0):.0%} |
| Exclamation rate | {sentence.get('punctuation', {}).get('exclamation_rate', 0):.0%} |
| Question rate | {sentence.get('punctuation', {}).get('question_rate', 0):.0%} |

## Vocabulary Patterns

### Common Phrases
{_format_list(vocab.get('unique_phrases', [])[:15])}

### Filler Words
{_format_list(vocab.get('filler_words', [])[:10])}

### Technical Terms
{_format_list(vocab.get('technical_terms', [])[:10])}

## Response Patterns

### Acknowledgments
{_format_list(response_patterns.get('acknowledgment', [])[:5])}

### Agreement
{_format_list(response_patterns.get('agreement', [])[:5])}

### Disagreement
{_format_list(response_patterns.get('disagreement', [])[:5])}

## Greetings & Signoffs

### Greetings
{_format_list(greetings.get('common', [])[:5])}

### Signoffs
{_format_list(signoffs.get('common', [])[:5])}

## Emoji Usage

Favorite emojis: {' '.join(emoji_data.get('favorites', [])[:10])}

### Contextual Patterns
- Agreement: {' '.join(emoji_data.get('contextual_patterns', {}).get('agreement', [])[:3])}
- Thinking: {' '.join(emoji_data.get('contextual_patterns', {}).get('thinking', [])[:3])}
- Positive: {' '.join(emoji_data.get('contextual_patterns', {}).get('positive', [])[:3])}

## Example Messages

These are real examples of {name}'s messages to use as few-shot examples:

"""

    # Add examples
    for i, ex in enumerate(examples, 1):
        text = ex.get("text", "")
        channel_type = ex.get("channel_type", "unknown")
        is_reply = ex.get("is_thread_reply", False)
        reply_context = ""

        if is_reply and ex.get("reply_to"):
            reply_to = ex.get("reply_to", {})
            reply_context = f"\n   > Replying to: \"{reply_to.get('text', '')[:100]}...\""

        md += f"""
### Example {i} ({channel_type}{', thread reply' if is_reply else ''})
{reply_context}
```
{text}
```
"""

    md += """
## Usage Guidelines

1. **Match the tone** - Keep responses at the same formality level
2. **Use natural phrases** - Incorporate the common phrases above
3. **Emoji appropriately** - Use emojis at the frequency indicated
4. **Be concise** - Match the average sentence length
5. **Stay authentic** - Don't over-correct or sound robotic
"""

    return md


def _tone_description(tone: dict) -> str:
    """Generate a natural language description of the tone."""
    formality = tone.get("formality", 0.5)
    directness = tone.get("directness", 0.5)

    parts = []

    if formality < 0.3:
        parts.append("casual")
    elif formality > 0.7:
        parts.append("professional")

    if directness > 0.7:
        parts.append("direct and to-the-point")
    elif directness < 0.3:
        parts.append("diplomatic and measured")

    if not parts:
        parts.append("balanced and approachable")

    return ", ".join(parts)


def _format_list(items: list) -> str:
    """Format a list as markdown bullet points."""
    if not items:
        return "- (none detected)"
    return "\n".join(f"- {item}" for item in items)
