#!/usr/bin/env python3
"""
Analyze performance scoring system event_type distribution across competencies.
Determines if the system disproportionately favors code-producing activities
over communication/leadership activities.
"""

COMPETENCY_DEFS = {
    "technical_contribution": {
        "base_points": 2,
        "event_types": [
            "mr_merged",
            "mr_opened",
            "issue_resolved",
            "commit",
            "pr_opened",
            "pr_merged",
            "debugging_outcome",
        ],
    },
    "technical_knowledge": {
        "base_points": 3,
        "event_types": [
            "commit",
            "alert_investigated",
            "architecture_decision",
            "debugging_outcome",
            "gdrive_doc_created",
            "gdrive_doc_contributed",
            "gdrive_sheet_created",
            "gdrive_sheet_contributed",
            "meeting_organized_architecture_review",
            "meeting_attended_architecture_review",
            "meeting_organized_training",
            "meeting_attended_training",
            "meeting_organized_incident_response",
            "meeting_attended_incident_response",
            "meeting_organized_code_review",
            "meeting_attended_code_review",
        ],
    },
    "creativity_innovation": {
        "base_points": 4,
        "event_types": [
            "pr_opened",
            "commit",
            "architecture_decision",
            "process_improvement",
            "gdrive_doc_created",
            "gdrive_doc_contributed",
            "gdrive_slides_created",
            "gdrive_slides_contributed",
            "meeting_organized_architecture_review",
            "meeting_attended_architecture_review",
        ],
    },
    "continuous_improvement": {
        "base_points": 3,
        "event_types": [
            "alert_investigated",
            "debugging_outcome",
            "process_improvement",
            "meeting_organized_retrospective",
            "meeting_attended_retrospective",
            "meeting_organized_incident_response",
            "meeting_attended_incident_response",
        ],
    },
    "leadership": {
        "base_points": 3,
        "event_types": [
            "meeting_participated",
            "architecture_decision",
            "collaboration_activity",
            "leadership_activity",
            "meeting_organized_planning",
            "meeting_organized_sprint_planning",
            "meeting_organized_architecture_review",
            "meeting_organized_all_hands",
            "meeting_organized_one_on_one",
            "meeting_attended_planning",
            "meeting_attended_sprint_planning",
            "meeting_attended_architecture_review",
            "meeting_attended_all_hands",
            "meeting_attended_one_on_one",
        ],
    },
    "collaboration": {
        "base_points": 2,
        "event_types": [
            "review_given",
            "pr_reviewed",
            "mr_review_given",
            "meeting_participated",
            "collaboration_activity",
            "recognition_given",
            "meeting_attended_cross_team",
            "meeting_organized_cross_team",
            "meeting_attended_code_review",
        ],
    },
    "mentorship": {
        "base_points": 3,
        "event_types": [
            "mr_review_given",
            "recognition_given",
            "meeting_organized_training",
            "meeting_attended_training",
            "meeting_organized_one_on_one",
            "meeting_attended_one_on_one",
            "meeting_organized_interview",
            "meeting_attended_interview",
            "meeting_organized_onboarding",
            "meeting_attended_onboarding",
            "meeting_organized_code_review",
            "meeting_attended_code_review",
        ],
    },
    "speaking_publicity": {
        "base_points": 4,
        "event_types": [
            "gdrive_slides_created",
            "gdrive_slides_contributed",
            "meeting_organized_presentation",
            "meeting_attended_presentation",
            "meeting_organized_sprint_review",
            "meeting_attended_sprint_review",
            "meeting_organized_all_hands",
        ],
    },
    "portfolio_impact": {
        "base_points": 4,
        "event_types": [],
    },
    "planning_execution": {
        "base_points": 2,
        "event_types": [
            "issue_created",
            "issue_opened",
            "issue_closed",
            "meeting_organized_sprint_planning",
            "meeting_attended_sprint_planning",
            "meeting_organized_planning",
            "meeting_attended_planning",
            "meeting_organized_standup",
            "session_documented",
            "gdrive_sheet_created",
            "gdrive_sheet_contributed",
        ],
    },
    "end_to_end_delivery": {
        "base_points": 3,
        "event_types": ["pr_merged", "mr_merged", "issue_resolved", "issue_closed"],
    },
    "opportunity_recognition": {
        "base_points": 4,
        "event_types": [
            "issue_opened",
            "issue_created",
            "pr_opened",
            "mr_opened",
            "process_improvement",
        ],
    },
    "customer_focus": {
        "base_points": 3,
        "event_types": [
            "issue_resolved",
            "issue_closed",
            "issue_opened",
            "alert_investigated",
            "customer_engagement",
            "meeting_organized_customer_meeting",
            "meeting_attended_customer_meeting",
        ],
    },
    "scope": {
        "base_points": 3,
        "event_types": [
            "mr_merged",
            "mr_opened",
            "pr_merged",
            "pr_opened",
            "issue_closed",
            "issue_created",
            "commit",
            "meeting_organized_all_hands",
            "meeting_attended_all_hands",
            "meeting_organized_cross_team",
            "meeting_attended_cross_team",
        ],
    },
    "evidence_record": {
        "base_points": 2,
        "event_types": [
            "issue_resolved",
            "issue_closed",
            "mr_merged",
            "pr_merged",
            "meeting_participated",
            "session_documented",
            "customer_engagement",
            "leadership_activity",
            "gdrive_doc_created",
            "gdrive_doc_contributed",
            "gdrive_sheet_created",
            "gdrive_sheet_contributed",
            "gdrive_slides_created",
            "gdrive_slides_contributed",
            "meeting_organized_standup",
            "meeting_organized_sprint_review",
            "meeting_organized_sprint_planning",
            "meeting_organized_retrospective",
            "meeting_organized_one_on_one",
            "meeting_organized_planning",
            "meeting_attended_standup",
            "meeting_attended_sprint_review",
            "meeting_attended_sprint_planning",
            "meeting_attended_retrospective",
            "meeting_attended_one_on_one",
            "meeting_attended_planning",
            "meeting_attended_general_meeting",
            "meeting_organized_general_meeting",
        ],
    },
    "execution_as_mentee": {
        "base_points": 2,
        "event_types": ["pr_reviewed", "mr_review_received"],
    },
}

# Bucket definitions
CODE_ARTIFACT = {
    "mr_merged",
    "mr_opened",
    "pr_opened",
    "pr_merged",
    "commit",
}
JIRA_TRACKING = {
    "issue_resolved",
    "issue_created",
    "issue_opened",
    "issue_closed",
}
MEETING_COMMUNICATION = {
    "meeting_participated",
    "meeting_organized_architecture_review",
    "meeting_attended_architecture_review",
    "meeting_organized_training",
    "meeting_attended_training",
    "meeting_organized_incident_response",
    "meeting_attended_incident_response",
    "meeting_organized_code_review",
    "meeting_attended_code_review",
    "meeting_organized_retrospective",
    "meeting_attended_retrospective",
    "meeting_organized_planning",
    "meeting_attended_planning",
    "meeting_organized_sprint_planning",
    "meeting_attended_sprint_planning",
    "meeting_organized_all_hands",
    "meeting_attended_all_hands",
    "meeting_organized_one_on_one",
    "meeting_attended_one_on_one",
    "meeting_attended_cross_team",
    "meeting_organized_cross_team",
    "meeting_organized_presentation",
    "meeting_attended_presentation",
    "meeting_organized_sprint_review",
    "meeting_attended_sprint_review",
    "meeting_organized_standup",
    "meeting_attended_standup",
    "meeting_organized_customer_meeting",
    "meeting_attended_customer_meeting",
    "meeting_organized_interview",
    "meeting_attended_interview",
    "meeting_organized_onboarding",
    "meeting_attended_onboarding",
    "meeting_attended_general_meeting",
    "meeting_organized_general_meeting",
}
DOCUMENT_KNOWLEDGE = {
    "gdrive_doc_created",
    "gdrive_doc_contributed",
    "gdrive_sheet_created",
    "gdrive_sheet_contributed",
    "gdrive_slides_created",
    "gdrive_slides_contributed",
    "session_documented",
    "architecture_decision",
}
REVIEW_COLLABORATION = {
    "review_given",
    "pr_reviewed",
    "mr_review_given",
    "mr_review_received",
    "recognition_given",
    "collaboration_activity",
    "leadership_activity",
}
OTHER = {
    "alert_investigated",
    "debugging_outcome",
    "process_improvement",
    "customer_engagement",
}


def categorize(event_type: str) -> str:
    if event_type in CODE_ARTIFACT:
        return "Code/Artifact"
    if event_type in JIRA_TRACKING:
        return "Jira/Tracking"
    if event_type in MEETING_COMMUNICATION:
        return "Meeting/Communication"
    if event_type in DOCUMENT_KNOWLEDGE:
        return "Document/Knowledge"
    if event_type in REVIEW_COLLABORATION:
        return "Review/Collaboration"
    if event_type in OTHER:
        return "Other"
    return "Other"


def main():
    # Build event_type -> competencies mapping
    event_to_comps: dict[str, set[str]] = {}
    comp_to_events: dict[str, list[str]] = {}

    for comp_id, defn in COMPETENCY_DEFS.items():
        event_types = defn.get("event_types", [])
        comp_to_events[comp_id] = event_types
        for et in event_types:
            event_to_comps.setdefault(et, set()).add(comp_id)

    # Unique event types
    all_events = sorted(event_to_comps.keys())

    # Categorize and count
    bucket_counts: dict[str, int] = {}
    bucket_event_counts: dict[str, int] = {}
    total_mappings = 0

    print("=" * 80)
    print("PERFORMANCE SCORING SYSTEM: EVENT_TYPE DISTRIBUTION ANALYSIS")
    print("=" * 80)

    print("\n## 1. ALL UNIQUE EVENT_TYPES BY BUCKET\n")
    print("| Event Type | Bucket | # Competencies |")
    print("|------------|--------|----------------|")

    for bucket in [
        "Code/Artifact",
        "Jira/Tracking",
        "Meeting/Communication",
        "Document/Knowledge",
        "Review/Collaboration",
        "Other",
    ]:
        bucket_counts[bucket] = 0
        bucket_event_counts[bucket] = 0

    for et in all_events:
        bucket = categorize(et)
        n_comps = len(event_to_comps[et])
        bucket_counts[bucket] += n_comps
        bucket_event_counts[bucket] += 1
        total_mappings += n_comps
        print(f"| {et} | {bucket} | {n_comps} |")

    print("\n## 2. DISTRIBUTION BY BUCKET (competency-event_type mappings)\n")
    print("| Bucket | Mappings | % of Total | Unique Event Types |")
    print("|--------|---------|------------|--------------------|")

    for bucket in [
        "Code/Artifact",
        "Jira/Tracking",
        "Meeting/Communication",
        "Document/Knowledge",
        "Review/Collaboration",
        "Other",
    ]:
        pct = 100 * bucket_counts[bucket] / total_mappings if total_mappings else 0
        print(
            f"| {bucket} | {bucket_counts[bucket]} | {pct:.1f}% | {bucket_event_counts[bucket]} |"
        )

    print(
        "\n## 3. COMPETENCIES WITH ZERO OR FEW MEETING/COMMUNICATION/DOCUMENT EVENT TYPES\n"
    )

    meeting_doc_buckets = {"Meeting/Communication", "Document/Knowledge"}

    for comp_id, events in comp_to_events.items():
        meeting_doc_count = sum(
            1 for e in events if categorize(e) in meeting_doc_buckets
        )
        code_jira_count = sum(
            1 for e in events if categorize(e) in {"Code/Artifact", "Jira/Tracking"}
        )
        total = len(events)
        if total == 0:
            print(f"- **{comp_id}**: 0 event types (portfolio_impact - empty)")
        elif meeting_doc_count == 0:
            print(
                f"- **{comp_id}**: 0 meeting/doc events, {code_jira_count} code/jira, {total} total"
            )
        elif meeting_doc_count <= 2 and total >= 4:
            print(
                f"- **{comp_id}**: {meeting_doc_count} meeting/doc, {code_jira_count} code/jira, {total} total"
            )

    print("\n## 4. COMPETENCIES MOST DEPENDENT ON CODE/JIRA EVENTS\n")

    comp_scores = []
    for comp_id, events in comp_to_events.items():
        if not events:
            continue
        code_jira = sum(
            1 for e in events if categorize(e) in {"Code/Artifact", "Jira/Tracking"}
        )
        pct = 100 * code_jira / len(events)
        comp_scores.append((comp_id, code_jira, len(events), pct))

    comp_scores.sort(key=lambda x: -x[3])
    print("| Competency | Code/Jira Events | Total | % Code/Jira |")
    print("|------------|------------------|-------|-------------|")
    for comp_id, cj, total, pct in comp_scores[:10]:
        print(f"| {comp_id} | {cj} | {total} | {pct:.0f}% |")

    print("\n## 5. SENIOR+ ASSESSMENT: LEADERSHIP/COMMUNICATION WORK\n")

    # Count what a Senior+ doing meetings, mentoring, reviews, strategy would generate
    senior_heavy_events = (
        MEETING_COMMUNICATION
        | DOCUMENT_KNOWLEDGE
        | REVIEW_COLLABORATION
        | {
            "architecture_decision",
            "leadership_activity",
            "collaboration_activity",
            "customer_engagement",
            "session_documented",
        }
    )

    # Competencies that reward senior work
    senior_friendly = set()
    for comp_id, events in comp_to_events.items():
        overlap = set(events) & senior_heavy_events
        if overlap:
            senior_friendly.add(comp_id)

    # Competencies that ONLY reward code/jira
    code_jira_only = set()
    for comp_id, events in comp_to_events.items():
        if not events:
            continue
        all_cj = all(
            categorize(e) in {"Code/Artifact", "Jira/Tracking"} for e in events
        )
        if all_cj:
            code_jira_only.add(comp_id)

    print("**Competencies with ZERO meeting/communication/document pathways:**")
    for c in sorted(code_jira_only):
        print(f"  - {c}")

    print("\n**Summary statistics:**")
    print(f"  - Total competency-event_type mappings: {total_mappings}")
    print(
        f"  - Code/Artifact + Jira/Tracking combined: {bucket_counts['Code/Artifact'] + bucket_counts['Jira/Tracking']} ({100 * (bucket_counts['Code/Artifact'] + bucket_counts['Jira/Tracking']) / total_mappings:.1f}%)"
    )
    print(
        f"  - Meeting/Communication + Document/Knowledge combined: {bucket_counts['Meeting/Communication'] + bucket_counts['Document/Knowledge']} ({100 * (bucket_counts['Meeting/Communication'] + bucket_counts['Document/Knowledge']) / total_mappings:.1f}%)"
    )
    print(
        f"  - Review/Collaboration: {bucket_counts['Review/Collaboration']} ({100 * bucket_counts['Review/Collaboration'] / total_mappings:.1f}%)"
    )

    print("\n**Verdict:**")
    code_jira_pct = (
        100
        * (bucket_counts["Code/Artifact"] + bucket_counts["Jira/Tracking"])
        / total_mappings
    )
    meeting_doc_pct = (
        100
        * (bucket_counts["Meeting/Communication"] + bucket_counts["Document/Knowledge"])
        / total_mappings
    )
    if code_jira_pct > meeting_doc_pct + 15:
        print("  YES - The system disproportionately favors code-producing activities.")
        print(
            f"  Code+Jira events account for {code_jira_pct:.1f}% of mappings vs {meeting_doc_pct:.1f}% for meeting/doc."
        )
    else:
        print(
            "  MIXED - Distribution is more balanced than extreme, but code/jira still dominant."
        )


if __name__ == "__main__":
    main()
