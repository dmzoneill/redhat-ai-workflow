# Session Bootstrap

> Session initialization and context loading

## Diagram

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant Tool as session_start
    participant Session as Session Manager
    participant Classifier as Intent Classifier
    participant Memory as Memory
    participant Persona as PersonaLoader
    participant Builder as SessionBuilder

    User->>Tool: session_start()

    Tool->>Session: Create/resume session
    Session-->>Tool: session_id

    Tool->>Classifier: Classify intent
    Classifier-->>Tool: intent, confidence

    alt Confidence > 80%
        Tool->>Persona: Auto-load persona
        Persona-->>Tool: Persona loaded
    end

    Tool->>Memory: Get current work
    Memory-->>Tool: Active issues, branches

    Tool->>Builder: Build context
    Builder-->>Tool: Bootstrap context

    Tool-->>User: Session info + context
```

## Bootstrap Phases

```mermaid
flowchart TB
    subgraph Phase1[1. Session Setup]
        CREATE[Create session]
        ASSIGN_ID[Assign session_id]
        STORE[Store in state]
    end

    subgraph Phase2[2. Intent Classification]
        PARSE[Parse session name]
        CLASSIFY[Classify intent]
        CONFIDENCE[Calculate confidence]
    end

    subgraph Phase3[3. Persona Loading]
        CHECK{Confidence > 80%?}
        AUTO_LOAD[Auto-load persona]
        SUGGEST[Suggest persona]
    end

    subgraph Phase4[4. Context Gathering]
        CURRENT_WORK[Get current work]
        ACTIVE_ISSUES[Get active issues]
        RECOMMENDATIONS[Generate recommendations]
    end

    Phase1 --> Phase2
    Phase2 --> Phase3
    CHECK -->|Yes| AUTO_LOAD
    CHECK -->|No| SUGGEST
    Phase3 --> Phase4
```

## Intent Classification

```mermaid
flowchart TB
    subgraph Input[Classification Input]
        SESSION_NAME[Session name]
        PROJECT[Project context]
        RECENT[Recent activity]
    end

    subgraph Keywords[Intent Keywords]
        CODE["code, MR, review → code_lookup"]
        DEPLOY["deploy, ephemeral → deployment"]
        DEBUG["alert, incident → troubleshooting"]
        DOCS["how, what, docs → documentation"]
    end

    subgraph Output[Classification Output]
        INTENT[Detected intent]
        CONF[Confidence score]
        PERSONA[Suggested persona]
    end

    Input --> Keywords
    Keywords --> Output
```

## Context Building

```mermaid
sequenceDiagram
    participant Builder as SessionBuilder
    participant Memory as Memory
    participant Jira as Jira (optional)
    participant Slack as Slack (optional)

    Builder->>Memory: Query current work
    Memory-->>Builder: Active issues

    Builder->>Memory: Query learned patterns
    Memory-->>Builder: Relevant patterns

    opt Include slow sources
        Builder->>Jira: Get issue details
        Jira-->>Builder: Issue data
        Builder->>Slack: Get recent messages
        Slack-->>Builder: Messages
    end

    Builder->>Builder: Format context
    Builder-->>Builder: Bootstrap markdown
```

## Bootstrap Output

```markdown
## 🎯 Bootstrap Context

**Session ID:** abc123-def456
**Detected Intent:** code_lookup (85% confidence)
**Auto-loading Persona:** developer

### Current Work
- **Active Issue:** AAP-12345 (In Progress)
- **Branch:** aap-12345-fix-auth
- **Last Commit:** 2h ago

### Recommended Actions
- Use `jira_view_issue` to check issue details
- Use `git_status` to see uncommitted changes
- Use `create_mr` when ready to submit

---
💡 Tip: Add `include_slow=true` to query Jira, GitLab
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| session_start | `session_tools.py` | Bootstrap tool |
| SessionBuilder | `session_builder.py` | Context building |
| Intent classifier | `session_builder.py` | Intent detection |

## Related Diagrams

- [Session Management](../01-server/workspace-tools.md)
- [Persona Loading Flow](../05-personas/persona-loading-flow.md)
- [Unified Memory Query](../06-memory/unified-memory-query.md)
