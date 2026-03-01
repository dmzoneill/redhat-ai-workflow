"""Timeline event helpers for sprint issues.

Extracted to avoid circular imports between daemon and mixins.
"""

# Maximum timeline entries per issue to prevent unbounded memory growth
MAX_TIMELINE_ENTRIES = 50


def _add_timeline_event(issue: dict, event: dict) -> None:
    """Add a timeline event to an issue, trimming old entries if needed."""
    if "timeline" not in issue:
        issue["timeline"] = []
    issue["timeline"].append(event)
    if len(issue["timeline"]) > MAX_TIMELINE_ENTRIES:
        issue["timeline"] = issue["timeline"][-MAX_TIMELINE_ENTRIES:]
