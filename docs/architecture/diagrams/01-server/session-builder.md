# Session Builder

> Super prompt context assembly from multiple sources

## Diagram

```mermaid
sequenceDiagram
    participant User as User
    participant Builder as SessionBuilder
    participant Persona as personas/
    participant Skills as skills/
    participant Memory as memory/
    participant External as External APIs

    User->>Builder: new SessionBuilder()
    Builder->>Builder: _load_config()

    User->>Builder: add_persona("developer")
    Builder->>Persona: Read developer.yaml
    Persona-->>Builder: persona context

    User->>Builder: add_skill("start_work")
    Builder->>Skills: Read start_work.yaml
    Skills-->>Builder: skill context

    User->>Builder: add_memory("state/current_work")
    Builder->>Memory: Read current_work.yaml
    Memory-->>Builder: memory context

    User->>Builder: add_jira_issue("AAP-12345")
    Builder->>External: Fetch issue (or placeholder)
    External-->>Builder: issue context

    User->>Builder: build()
    Builder-->>User: Assembled super prompt
```

## Class Structure

```mermaid
classDiagram
    class SessionBuilder {
        +context_sections: dict~str,str~
        +token_counts: dict~str,int~
        +config: dict
        -_load_config(): dict
        +add_persona(id): bool
        +add_skill(id): bool
        +add_memory(path): bool
        +add_jira_issue(key, data): bool
        +add_slack_results(query, results): bool
        +add_code_results(query, results): bool
        +add_meeting_context(id, excerpts): bool
        +add_custom_context(title, content): bool
        +build(): str
        +get_token_summary(): dict
        +preview(): dict
        +export_template(name, desc): dict
    }

    class ContextSources {
        <<enumeration>>
        persona
        skills
        memory
        jira
        slack
        code
        meeting
        custom
    }

    class TokenSummary {
        +sections: dict~str,int~
        +total: int
        +warning: bool
        +danger: bool
    }

    SessionBuilder --> ContextSources : assembles
    SessionBuilder --> TokenSummary : produces
```

## Context Assembly Flow

```mermaid
flowchart TB
    subgraph Sources[Context Sources]
        PERSONA[Persona YAML]
        SKILL[Skill YAML]
        MEMORY[Memory YAML]
        JIRA[Jira API]
        SLACK[Slack Search]
        CODE[Code Search]
        MEETING[Meeting Transcripts]
    end

    subgraph Builder[SessionBuilder]
        ADD[add_* methods]
        SECTIONS[context_sections dict]
        TOKENS[token_counts dict]
    end

    subgraph Output[Output]
        BUILD[build method]
        PROMPT[Super Prompt]
        PREVIEW[preview method]
        SUMMARY[Token Summary]
    end

    PERSONA --> ADD
    SKILL --> ADD
    MEMORY --> ADD
    JIRA --> ADD
    SLACK --> ADD
    CODE --> ADD
    MEETING --> ADD

    ADD --> SECTIONS
    ADD --> TOKENS

    SECTIONS --> BUILD
    BUILD --> PROMPT
    TOKENS --> PREVIEW
    PREVIEW --> SUMMARY
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SessionBuilder | `server/session_builder.py` | Main builder class |
| estimate_tokens | `server/session_builder.py` | Token estimation (4 chars/token) |
| build_auto_context | `server/session_builder.py` | Auto-build from issue key |
| WORKSPACE_ROOT | `server/session_builder.py` | Project root path |

## Section Order

The `build()` method assembles sections in this order:

1. persona - System prompt and tool context
2. jira - Issue details
3. memory - Current work, patterns
4. skills - Workflow definitions
5. slack - Related messages
6. code - Related code snippets
7. meeting - Transcript excerpts
8. (custom sections)

## Related Diagrams

- [MCP Server Core](./mcp-server-core.md)
- [Memory Architecture](../06-memory/memory-architecture.md)
- [Context Gathering Flow](../08-data-flows/context-gathering.md)
