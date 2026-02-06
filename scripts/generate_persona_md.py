#!/usr/bin/env python3
"""Generate persona markdown from style profile."""

import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
STYLE_DIR = PROJECT_ROOT / "memory" / "style"
PERSONAS_DIR = PROJECT_ROOT / "personas"

# Load profile
profile_file = STYLE_DIR / "dave_style_profile.yaml"
try:
    with open(profile_file) as f:
        profile = yaml.safe_load(f)
except FileNotFoundError:
    print(f"❌ Profile file not found: {profile_file}")
    sys.exit(1)
except yaml.YAMLError as e:
    print(f"❌ Invalid YAML in profile: {e}")
    sys.exit(1)

# Load corpus for examples
corpus_file = STYLE_DIR / "slack_corpus.jsonl"
messages = []
try:
    with open(corpus_file) as f:
        for line in f:
            if line.strip():
                messages.append(json.loads(line))
except FileNotFoundError:
    print(f"⚠️ Corpus file not found: {corpus_file}, continuing without examples")
except json.JSONDecodeError as e:
    print(f"⚠️ Invalid JSON in corpus: {e}, continuing with partial data")

# Extract profile data
tone = profile.get("tone", {})
vocab = profile.get("vocabulary", {})
emoji_data = profile.get("emoji", {})
sentence = profile.get("sentence_patterns", {})
greetings = profile.get("greetings", {})
signoffs = profile.get("signoffs", {})
response_patterns = profile.get("response_patterns", {})
meta = profile.get("meta", {})

# Select DIVERSE example messages for better few-shot learning
examples = []
tech_terms = [
    "pod",
    "api",
    "deploy",
    "merge",
    "branch",
    "test",
    "debug",
    "config",
    "build",
    "pr",
    "mr",
    "jira",
    "git",
    "k8s",
    "pipeline",
]

# Categorize messages
short_msgs = []  # < 40 chars - quick responses
medium_msgs = []  # 40-120 chars - typical messages
long_msgs = []  # 120-250 chars - detailed responses
questions = []  # Contains ?
technical = []  # Has tech terms
acknowledgments = []  # Short acks like "k", "got it", etc

ack_patterns = ["got it", "makes sense", "sounds good", "ok", "k", "ack", "copy", "noted", "thanks", "cheers"]

for msg in messages:
    text = msg.get("text", "")
    # Skip messages with special formatting or too short
    if text.startswith("<") or "```" in text or len(text) < 3:
        continue

    length = len(text)
    text_lower = text.lower().strip()

    # Categorize
    if length < 40:
        short_msgs.append(msg)
        if any(text_lower.startswith(a) or text_lower == a for a in ack_patterns):
            acknowledgments.append(msg)
    elif length < 120:
        medium_msgs.append(msg)
    elif length < 250:
        long_msgs.append(msg)

    if "?" in text and length > 15:
        questions.append(msg)

    if any(t in text_lower for t in tech_terms):
        technical.append(msg)

# Select diverse examples (30 total)
# 5 acknowledgments, 5 short, 8 medium, 5 long, 4 questions, 3 technical
import random

random.seed(42)  # Reproducible


def pick_unique(source, count, existing):
    """Pick unique messages not already selected."""
    picked = []
    for msg in source:
        if msg not in existing and len(picked) < count:
            picked.append(msg)
    return picked


examples.extend(pick_unique(acknowledgments[:20], 5, examples))
examples.extend(pick_unique(short_msgs[10:50], 5, examples))
examples.extend(pick_unique(medium_msgs[:30], 8, examples))
examples.extend(pick_unique(long_msgs[:20], 5, examples))
examples.extend(pick_unique(questions[:20], 4, examples))
examples.extend(pick_unique(technical[:20], 3, examples))

# Limit to 30
examples = examples[:30]

# Build markdown
lines = []

lines.append("# Dave Communication Style")
lines.append("")
lines.append(
    f"This persona mimics Dave's natural communication patterns based on analysis of {meta.get('messages_analyzed', len(messages))} Slack messages."
)
lines.append("")
lines.append("## Style Overview")
lines.append("")
lines.append("| Attribute | Value |")
lines.append("|-----------|-------|")
lines.append(f"| Formality | {tone.get('formality', 0.5):.0%} |")
lines.append(f"| Directness | {tone.get('directness', 0.5):.0%} |")
lines.append(f"| Avg sentence length | {sentence.get('avg_length', 12):.0f} words |")
lines.append(f"| Emoji usage | {emoji_data.get('frequency', 0):.0%} |")
lines.append(f"| Exclamation rate | {sentence.get('punctuation', {}).get('exclamation_rate', 0):.0%} |")
lines.append(f"| Question rate | {sentence.get('punctuation', {}).get('question_rate', 0):.0%} |")
lines.append(f"| Capitalization | {sentence.get('capitalization', 'mixed')} |")
lines.append("")
lines.append("## Key Style Points")
lines.append("")
lines.append("- **Casual and direct** - Low formality (35%), high directness (77%)")
lines.append("- **Lowercase preferred** - Rarely capitalizes")
lines.append('- **Concise acknowledgments** - Uses "k", "ack", "got it"')
lines.append("- **Technical vocabulary** - Frequently uses dev terms (debug, test, merge, pod, api)")
lines.append("")
lines.append("## Response Patterns")
lines.append("")
lines.append("### Acknowledgments")
for a in response_patterns.get("acknowledgment", [])[:8]:
    lines.append(f"- {a}")
lines.append("")
lines.append("### Agreement")
for a in response_patterns.get("agreement", [])[:8]:
    lines.append(f"- {a}")
lines.append("")
lines.append("### Disagreement")
for d in response_patterns.get("disagreement", [])[:5]:
    lines.append(f"- {d}")
lines.append("")
lines.append("## Greetings & Signoffs")
lines.append("")
lines.append("### Greetings")
for g in greetings.get("common", [])[:5]:
    lines.append(f"- {g}")
lines.append("")
lines.append("### Signoffs")
for s in signoffs.get("common", [])[:5]:
    lines.append(f"- {s}")
lines.append("")
lines.append("## Filler Words (use naturally)")
lines.append(", ".join(vocab.get("filler_words", [])[:10]))
lines.append("")
lines.append("## Example Messages")
lines.append("")

for i, ex in enumerate(examples, 1):
    text = ex.get("text", "")
    channel_type = ex.get("channel_type", "unknown")
    lines.append(f"### Example {i} ({channel_type})")
    lines.append("```")
    lines.append(text)
    lines.append("```")
    lines.append("")

lines.append("## Usage Guidelines")
lines.append("")
lines.append("1. **Stay casual** - Use lowercase, short responses")
lines.append("2. **Be direct** - Get to the point quickly")
lines.append('3. **Use familiar phrases** - "got it", "makes sense", "let me check"')
lines.append("4. **Technical when needed** - Use dev terminology naturally")
lines.append("5. **Minimal punctuation** - Few exclamations, occasional questions")

# Write file
md_file = PERSONAS_DIR / "dave.md"
try:
    PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
    with open(md_file, "w") as f:
        f.write("\n".join(lines))
    print(f"✅ Persona markdown saved to: {md_file}")
except OSError as e:
    print(f"❌ Failed to write persona file: {e}")
    sys.exit(1)
print(f"   - {len(examples)} example messages included")
print()
print("To use the persona:")
print('  persona_load("dave")')
