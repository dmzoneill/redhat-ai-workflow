#!/usr/bin/env python3
"""
Analyze keyword/phrase bias in performance scoring: code vs communication/leadership.
Computes signal counts for realistic events to quantify bias.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.stats.scorer import COMPETENCY_DEFS, DEFAULT_GLOBALS

# Meeting classification boost text (from meeting_collector.py)
CLASSIFICATION_BOOST = {
    "standup": "standup scrum daily sync agile ceremony",
    "sprint_planning": "sprint planning capacity backlog agile ceremony",
    "sprint_review": "sprint review demo showcase presentation agile ceremony",
    "retrospective": "retro retrospective improvement process agile ceremony",
    "one_on_one": "mentorship coaching leadership one-on-one feedback",
    "architecture_review": "architecture design review technical documentation",
    "interview": "interview hiring talent mentorship leadership",
    "training": "training onboarding mentorship knowledge sharing workshop",
    "incident_response": "incident response operations troubleshooting",
    "all_hands": "all-hands organization leadership team communication",
    "planning": "planning roadmap strategy leadership execution",
    "customer_meeting": "customer stakeholder engagement feedback",
    "cross_team": "cross-team collaboration scope community working group",
    "presentation": "presentation demo speaking talk slides",
    "code_review": "code review mentorship technical knowledge sharing",
    "general_meeting": "meeting collaboration team",
}


def count_signals(
    text: str, event_type: str, defs: dict = None, debug_comp: str = None
) -> dict[str, int]:
    """Count signals per competency for given classification_text and event_type."""
    defs = defs or COMPETENCY_DEFS
    text_lower = text.lower()
    counts = {}
    for comp_id, defn in defs.items():
        signals = 0
        if event_type in defn.get("event_types", []):
            signals += 1
        for phrase in defn.get("phrases", []):
            if phrase in text_lower:
                signals += 1
        for kw in defn.get("keywords", []):
            if kw in text_lower:
                signals += 1
        counts[comp_id] = signals
    return counts


def build_meeting_text(
    title: str, classification: str, is_organizer: bool = False
) -> str:
    """Build classification text as meeting collector does."""
    parts = [title, classification, CLASSIFICATION_BOOST.get(classification, "")]
    if is_organizer:
        parts.append("organized led facilitated leadership")
    return " ".join(p for p in parts if p)


def main():
    min_sig = DEFAULT_GLOBALS["min_signals"]

    examples = [
        {
            "name": "Commit: fix(billing): migrate database schema",
            "text": "AAP-12345 - fix(billing): migrate database schema to add subscription field",
            "event_type": "commit",
        },
        {
            "name": "Jira resolved: Implement Redis caching",
            "text": "AAP-12345: Implement Redis caching for API endpoint",
            "event_type": "issue_resolved",
        },
        {
            "name": "Meeting: Weekly Architecture Review (attended)",
            "text": build_meeting_text(
                "Weekly Architecture Review", "architecture_review"
            ),
            "event_type": "meeting_attended_architecture_review",
        },
        {
            "name": "Meeting: 1:1 with John (attended)",
            "text": build_meeting_text("1:1 with John", "one_on_one"),
            "event_type": "meeting_attended_one_on_one",
        },
        {
            "name": "Meeting: Sprint Planning (attended)",
            "text": build_meeting_text("Sprint Planning", "sprint_planning"),
            "event_type": "meeting_attended_sprint_planning",
        },
        {
            "name": "Google Doc: ANSTRAT-123 Technical Design",
            "text": "ANSTRAT-123 Technical Design - Redis Migration",
            "event_type": "gdrive_doc_created",
        },
    ]

    # GDrive doc would get boost from architecture_doc classification
    # For this analysis we use raw title only (no GDrive boost) to show inherent bias
    gdrive_arch_text = (
        "ANSTRAT-123 Technical Design - Redis Migration "
        "architecture design review adr rfc documentation"
    )
    examples[5]["text"] = gdrive_arch_text

    print("=" * 80)
    print("KEYWORD/PHRASE BIAS ANALYSIS: Code vs Communication/Leadership")
    print("=" * 80)
    print(f"\nmin_signals threshold: {min_sig}")
    print()

    total_activated = 0
    total_points = 0

    for ex in examples:
        counts = count_signals(ex["text"], ex["event_type"])
        activated = {c: s for c, s in counts.items() if s >= min_sig}
        points = sum(COMPETENCY_DEFS[c]["base_points"] for c in activated)
        total_activated += len(activated)
        total_points += points

        print(f"--- {ex['name']} ---")
        print(f"Event type: {ex['event_type']}")
        print(f"Classification text (first 100 chars): {ex['text'][:100]}...")
        print(f"Competencies activated (>= {min_sig} signals): {len(activated)}")
        for c in sorted(activated.keys()):
            base = COMPETENCY_DEFS[c]["base_points"]
            print(f"  - {c}: {activated[c]} signals -> {base} pts")
        print(f"Total points: {points}")
        print()

    # Keyword overlap analysis
    print("=" * 80)
    print("KEYWORD OVERLAP: Competencies sharing keywords with technical_contribution")
    print("=" * 80)
    tc_kw = set(COMPETENCY_DEFS["technical_contribution"]["keywords"])
    tc_ph = set(COMPETENCY_DEFS["technical_contribution"]["phrases"])
    for comp_id, defn in COMPETENCY_DEFS.items():
        if comp_id == "technical_contribution":
            continue
        kw_overlap = tc_kw & set(defn.get("keywords", []))
        ph_overlap = tc_ph & set(defn.get("phrases", []))
        if kw_overlap or ph_overlap:
            print(
                f"  {comp_id}: keywords={kw_overlap or 'none'}, phrases={ph_overlap or 'none'}"
            )

    # Meeting boost sufficiency
    print("\n" + "=" * 80)
    print("MEETING BOOST SUFFICIENCY")
    print("=" * 80)
    for title, classification in [
        ("1:1 with John", "one_on_one"),
        ("Team Standup", "standup"),
        ("Weekly Sync", "general_meeting"),
    ]:
        text = build_meeting_text(title, classification)
        counts = count_signals(text, f"meeting_attended_{classification}")
        activated = sum(1 for s in counts.values() if s >= min_sig)
        print(
            f"  '{title}' ({classification}): {activated} competencies, text='{text[:80]}...'"
        )

    # Standup edge case: only matches planning_execution via "standup"
    standup_text = build_meeting_text("Team Standup", "standup")
    standup_counts = count_signals(standup_text, "meeting_attended_standup")
    print(f"\n  'Team Standup' signal breakdown:")
    for c, s in sorted(standup_counts.items(), key=lambda x: -x[1]):
        if s > 0:
            print(f"    {c}: {s}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
