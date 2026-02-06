# Skill Hooks

> Event-driven notifications during skill execution

## Diagram

```mermaid
classDiagram
    class RateLimiter {
        +window_seconds: int
        +max_per_author: int
        +max_tracked_authors: int
        -_counts: dict
        +can_send(author_id): bool
        +record(author_id): void
    }

    class SkillHooks {
        +rate_limiter: RateLimiter
        +on_review_started(mr, author): void
        +on_review_complete(mr, summary): void
        +on_issue_found(mr, issue): void
        +send_dm(user_id, message): void
        +send_channel(channel, message): void
    }

    SkillHooks --> RateLimiter
```

## Hook Flow

```mermaid
sequenceDiagram
    participant Skill as Skill Engine
    participant Hooks as Skill Hooks
    participant Limiter as Rate Limiter
    participant Slack as Slack API

    Skill->>Hooks: on_review_started(mr, author)
    Hooks->>Limiter: can_send(author_id)?
    alt Under limit
        Limiter-->>Hooks: true
        Hooks->>Slack: Send DM to author
        Hooks->>Limiter: record(author_id)
    else Over limit
        Limiter-->>Hooks: false
        Note over Hooks: Skip notification
    end

    Skill->>Hooks: on_review_complete(mr, summary)
    Hooks->>Slack: Post to team channel
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SkillHooks | `scripts/skill_hooks.py` | Main hooks class |
| RateLimiter | `scripts/skill_hooks.py` | Spam prevention |

## Rate Limiting

Prevents notification spam to individual users:

| Setting | Default | Description |
|---------|---------|-------------|
| `window_seconds` | 300 | Rate limit window (5 min) |
| `max_per_author` | 3 | Max notifications per window |
| `max_tracked_authors` | 500 | Memory limit for tracking |

## Hook Events

### on_review_started

Fired when a code review begins:
```python
await hooks.on_review_started(
    mr={"iid": 123, "title": "Fix bug"},
    author={"id": "U123", "name": "Dave"}
)
# → DM to author: "Starting review of MR !123"
```

### on_review_complete

Fired when review finishes:
```python
await hooks.on_review_complete(
    mr={"iid": 123, "title": "Fix bug"},
    summary={"issues": 2, "suggestions": 5}
)
# → Channel post: "Review complete: 2 issues, 5 suggestions"
```

### on_issue_found

Fired for each significant issue:
```python
await hooks.on_issue_found(
    mr={"iid": 123},
    issue={"severity": "high", "file": "api.py", "line": 42}
)
# → DM to author: "Found high-severity issue in api.py:42"
```

## Message Format

Notifications are terse and actionable:

```
📝 Review started: MR !123 "Fix authentication bug"

⚠️ Found 2 issues in your MR !123:
  • High: SQL injection risk in api.py:42
  • Medium: Missing error handling in utils.py:18

✅ Review complete: MR !123
  Issues: 2 | Suggestions: 5
  View: https://gitlab.com/...
```

## Integration

Used by:
- **review-pr** skill: Notifies authors during review
- **review-all-prs** skill: Batch review notifications
- **sprint-autopilot** skill: Progress updates

## Related Diagrams

- [Skill Engine](../04-skills/skill-engine-architecture.md)
- [Slack Integration](../07-integrations/slack-integration.md)
- [Ralph Loop](./ralph-loop.md)
