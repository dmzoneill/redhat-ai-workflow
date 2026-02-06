# Slack Persona Tools

> aa_slack_persona module for Slack conversation vector search and persona context

## Diagram

```mermaid
classDiagram
    class SlackPersonaTools {
        +slack_persona_sync(mode, months): str
        +slack_persona_search(query, limit): str
        +slack_persona_status(): str
        +slack_persona_context(query): str
    }

    class VectorStore {
        +index_messages(messages)
        +search(query, k): list
        +get_stats(): dict
    }

    class SlackExporter {
        +export_conversations(months)
        +export_incremental(days)
    }

    SlackPersonaTools --> VectorStore : uses
    SlackPersonaTools --> SlackExporter : uses
```

## Sync Flow

```mermaid
sequenceDiagram
    participant Tool as Sync Tool
    participant Export as Slack Exporter
    participant Slack as Slack API
    participant Embed as Embedder
    participant Vector as Vector DB

    Tool->>Export: slack_persona_sync()
    Export->>Slack: Fetch conversations
    Slack-->>Export: Messages + threads
    Export->>Export: Format messages
    Export->>Embed: Generate embeddings
    Embed-->>Export: Vectors
    Export->>Vector: Store in LanceDB
    Vector-->>Tool: Sync complete
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_slack_persona/src/` | MCP tool definitions |
| sync.py | `tool_modules/aa_slack_persona/src/` | Sync implementation |

## Tool Summary

| Tool | Description |
|------|-------------|
| `slack_persona_sync` | Full or incremental sync of Slack conversations |
| `slack_persona_search` | Semantic search across past conversations |
| `slack_persona_status` | Get current sync status and stats |
| `slack_persona_context` | Get context for a query (persona injection) |

## Sync Modes

| Mode | Description |
|------|-------------|
| `incremental` | Sync only recent messages (last N days) |
| `full` | Full sync of all conversations (last N months) |

## Usage Examples

```python
# Incremental sync (last day)
result = await slack_persona_sync(mode="incremental", days=1)

# Full sync (last 12 months)
result = await slack_persona_sync(mode="full", months=12)

# Search conversations
result = await slack_persona_search("RDS configuration issues", limit=5)

# Get context for persona response
result = await slack_persona_context("How do I configure alerts?")
```

## Vector Storage

Conversations are stored in LanceDB for semantic search:

```
~/.config/aa-workflow/vectors/slack_persona/
├── data/           # LanceDB data files
└── metadata.json   # Sync metadata
```

## Related Diagrams

- [Slack Tools](./slack-tools.md)
- [Code Search Tools](./code-search-tools.md)
- [Memory Architecture](../06-memory/memory-architecture.md)
