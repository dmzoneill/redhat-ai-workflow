# Unified Memory Query

> memory_ask: intelligent context gathering

## Diagram

```mermaid
flowchart TB
    subgraph Input[Query Input]
        QUESTION[question: string]
        SOURCES[sources: optional]
        INCLUDE_SLOW[include_slow: bool]
    end

    subgraph Classification[Intent Classification]
        CLASSIFY[Classify question intent]
        SELECT[Select relevant sources]
    end

    subgraph FastSources[Fast Sources < 2s]
        YAML[YAML Memory]
        CODE[Code Search]
        SLACK[Slack History]
    end

    subgraph SlowSources[Slow Sources > 2s]
        JIRA[Jira]
        GITLAB[GitLab]
        INSCOPE[InScope]
        CALENDAR[Calendar]
        GMAIL[Gmail]
        GDRIVE[GDrive]
    end

    subgraph Output[Query Output]
        MERGE[Merge Results]
        RANK[Rank by Relevance]
        FORMAT[Format Markdown]
    end

    Input --> Classification
    Classification --> FastSources
    Classification -->|include_slow| SlowSources
    FastSources --> Output
    SlowSources --> Output
```

## Query Flow

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant Tool as memory_ask
    participant Classifier as Intent Classifier
    participant Router as Source Router
    participant Fast as Fast Sources
    participant Slow as Slow Sources
    participant Formatter as Result Formatter

    User->>Tool: memory_ask("What am I working on?")
    Tool->>Classifier: Classify intent
    Classifier-->>Tool: intent: status_check

    Tool->>Router: Get sources for intent
    Router-->>Tool: [yaml, slack]

    par Query fast sources
        Tool->>Fast: Query YAML
        Fast-->>Tool: yaml_results
        Tool->>Fast: Query Slack
        Fast-->>Tool: slack_results
    end

    Tool->>Formatter: Format results
    Formatter-->>Tool: Markdown response

    Tool-->>User: "## Current Work\n..."
```

## Source Selection

```mermaid
flowchart TB
    subgraph Intent[Intent Types]
        STATUS[status_check]
        DOCS[documentation]
        ISSUE[issue_context]
        CODE_Q[code_lookup]
        HISTORY[history_lookup]
    end

    subgraph Sources[Source Selection]
        S_STATUS[yaml, slack]
        S_DOCS[inscope, yaml]
        S_ISSUE[jira, yaml]
        S_CODE[code_search, yaml]
        S_HISTORY[sessions, yaml]
    end

    STATUS --> S_STATUS
    DOCS --> S_DOCS
    ISSUE --> S_ISSUE
    CODE_Q --> S_CODE
    HISTORY --> S_HISTORY
```

## Latency Classes

| Class | Sources | Latency | Use Case |
|-------|---------|---------|----------|
| Fast | yaml, code, slack | <2s | Bootstrap, quick queries |
| Slow | jira, gitlab, inscope, calendar, gmail, gdrive | >2s | Comprehensive search |

## Output Format

```markdown
## 🎯 Query: What am I working on?

**Intent:** status_check

### From YAML Memory
- Active issue: AAP-12345 (In Progress)
- Branch: aap-12345-fix-auth
- Last commit: 2h ago

### From Slack
- Recent discussion in #team about AAP-12345
- Mentioned by @colleague 1h ago

---
💡 Tip: Add `include_slow=true` to search Jira, GitLab
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| memory_ask | `memory_unified.py` | Main tool |
| Intent classifier | `memory_unified.py` | Classify questions |
| Source router | `memory_unified.py` | Select sources |
| Adapters | `*/adapter.py` | Source implementations |

## Related Diagrams

- [Memory Architecture](./memory-architecture.md)
- [Adapter Pattern](../03-tools/adapter-pattern.md)
- [Session Bootstrap](../08-data-flows/session-bootstrap.md)
