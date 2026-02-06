# Memory Query Flow

> Data flow for memory queries

## Diagram

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant Tool as memory_ask
    participant Router as Source Router
    participant Fast as Fast Sources
    participant Slow as Slow Sources
    participant Formatter as Result Formatter

    User->>Tool: memory_ask("What am I working on?")

    Tool->>Router: Route query
    Router->>Router: Classify intent
    Router->>Router: Select sources

    par Query fast sources (parallel)
        Router->>Fast: Query YAML
        Fast-->>Router: yaml_results
        Router->>Fast: Query Code
        Fast-->>Router: code_results
        Router->>Fast: Query Slack
        Fast-->>Router: slack_results
    end

    opt include_slow=true
        par Query slow sources (parallel)
            Router->>Slow: Query Jira
            Slow-->>Router: jira_results
            Router->>Slow: Query GitLab
            Slow-->>Router: gitlab_results
        end
    end

    Router->>Formatter: Merge results
    Formatter->>Formatter: Rank by relevance
    Formatter->>Formatter: Format markdown
    Formatter-->>Tool: Formatted response
    Tool-->>User: Response
```

## Source Selection

```mermaid
flowchart TB
    subgraph Intent[Intent Classification]
        QUESTION[User question]
        CLASSIFY[Classify intent]
    end

    subgraph Selection[Source Selection]
        STATUS[status_check → yaml, slack]
        DOCS[documentation → inscope, yaml]
        ISSUE[issue_context → jira, yaml]
        CODE[code_lookup → code_search, yaml]
    end

    subgraph Latency[Latency Filter]
        FAST_ONLY[Fast sources only]
        INCLUDE_SLOW[Include slow sources]
    end

    Intent --> Selection
    Selection --> Latency
```

## Adapter Query Flow

```mermaid
sequenceDiagram
    participant Router as Source Router
    participant Adapter as Memory Adapter
    participant Source as Data Source

    Router->>Adapter: query(question)

    Adapter->>Adapter: Build query
    Adapter->>Source: Execute query
    Source-->>Adapter: Raw results

    Adapter->>Adapter: Parse results
    Adapter->>Adapter: Calculate relevance
    Adapter-->>Router: Ranked results
```

## Result Merging

```mermaid
flowchart TB
    subgraph Sources[Source Results]
        YAML_RES[YAML: 3 results]
        CODE_RES[Code: 2 results]
        JIRA_RES[Jira: 1 result]
    end

    subgraph Merge[Merge Process]
        COLLECT[Collect all results]
        DEDUPE[Remove duplicates]
        RANK[Rank by relevance]
        LIMIT[Limit to top N]
    end

    subgraph Output[Final Output]
        FORMAT[Format markdown]
        GROUP[Group by source]
    end

    Sources --> Merge
    Merge --> Output
```

## Query Caching

```mermaid
flowchart TB
    QUERY[Query received]
    CACHE_CHECK{In cache?}
    CACHE_HIT[Return cached]
    CACHE_MISS[Execute query]
    STORE[Store in cache]
    RETURN[Return result]

    QUERY --> CACHE_CHECK
    CACHE_CHECK -->|Yes| CACHE_HIT
    CACHE_CHECK -->|No| CACHE_MISS
    CACHE_MISS --> STORE
    STORE --> RETURN
    CACHE_HIT --> RETURN
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| memory_ask | `memory_unified.py` | Main tool |
| Source router | `memory_unified.py` | Query routing |
| Adapters | `*/adapter.py` | Source implementations |

## Related Diagrams

- [Unified Memory Query](../06-memory/unified-memory-query.md)
- [Adapter Pattern](../03-tools/adapter-pattern.md)
- [Memory Architecture](../06-memory/memory-architecture.md)
