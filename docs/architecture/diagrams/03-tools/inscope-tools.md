# InScope Tools

> aa_inscope module for internal documentation search

## Diagram

```mermaid
sequenceDiagram
    participant Tool as InScope Tool
    participant Client as HTTP Client
    participant InScope as InScope API
    participant Index as Document Index

    Tool->>Client: Build query
    Client->>InScope: POST /api/search
    InScope->>Index: Search documents
    Index-->>InScope: Matching docs
    InScope-->>Client: Search results
    Client-->>Tool: Formatted results

    Tool->>Tool: Extract relevant sections
    Tool-->>Tool: Format for Claude
```

## Class Structure

```mermaid
classDiagram
    class InScopeBasic {
        +inscope_search(query): list
        +inscope_ask(question): str
        +inscope_get_document(id): dict
        +inscope_list_sources(): list
    }

    class InScopeClient {
        +base_url: str
        +api_key: str
        +search(query, filters): list
        +ask(question): str
        +get_document(id): dict
    }

    class InScopeAdapter {
        +query(question): list
        +search(query): list
        +get_sources(): list
    }

    InScopeBasic --> InScopeClient
    InScopeAdapter --> InScopeBasic
```

## Search Flow

```mermaid
flowchart TB
    subgraph Input[Query Input]
        QUESTION[Natural Language Question]
        FILTERS[Source Filters]
    end

    subgraph Search[Search Process]
        EMBED[Generate Embedding]
        VECTOR[Vector Search]
        KEYWORD[Keyword Search]
        HYBRID[Hybrid Ranking]
    end

    subgraph Results[Results Processing]
        DOCS[Matching Documents]
        EXTRACT[Extract Sections]
        SUMMARIZE[Summarize Answer]
    end

    QUESTION --> EMBED
    QUESTION --> KEYWORD
    FILTERS --> VECTOR
    FILTERS --> KEYWORD

    EMBED --> VECTOR
    VECTOR --> HYBRID
    KEYWORD --> HYBRID

    HYBRID --> DOCS
    DOCS --> EXTRACT
    EXTRACT --> SUMMARIZE
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_inscope/src/` | Search operations |
| adapter.py | `tool_modules/aa_inscope/src/` | Memory adapter |

## Tool Summary

| Tool | Description |
|------|-------------|
| `inscope_search` | Search documentation |
| `inscope_ask` | Ask question, get answer |
| `inscope_get_document` | Get specific document |
| `inscope_list_sources` | List available sources |

## Document Sources

| Source | Content Type |
|--------|--------------|
| Confluence | Wiki pages |
| GitLab | Repository docs |
| Google Docs | Shared documents |
| Notion | Team knowledge |
| Internal wikis | Company docs |

## Configuration

```json
{
  "inscope": {
    "base_url": "https://inscope.example.com",
    "api_key_env": "INSCOPE_API_KEY",
    "default_sources": ["confluence", "gitlab"],
    "max_results": 10
  }
}
```

## Query Examples

```
# Documentation queries
"How do I deploy to production?"
"What is the release process for Konflux?"
"Where is the database schema documented?"

# Specific lookups
"RDS configuration guide"
"Slack integration setup"
"CI/CD pipeline documentation"
```

## Memory Integration

```mermaid
flowchart TB
    subgraph Query[Memory Query]
        ASK[memory_ask]
        SOURCES[sources: inscope]
    end

    subgraph InScope[InScope Search]
        SEARCH[inscope_search]
        RESULTS[Documentation results]
    end

    subgraph Response[Response]
        FORMAT[Format for Claude]
        CONTEXT[Add to context]
    end

    ASK --> SOURCES
    SOURCES --> SEARCH
    SEARCH --> RESULTS
    RESULTS --> FORMAT
    FORMAT --> CONTEXT
```

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Memory Abstraction](../06-memory/memory-abstraction.md)
- [Memory Query Flow](../06-memory/memory-query-flow.md)
