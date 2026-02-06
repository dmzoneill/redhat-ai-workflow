# Memory Abstraction Layer

> Unified interface for querying all memory sources

## Diagram

```mermaid
graph TB
    subgraph Interface[MemoryInterface]
        QUERY[query]
        SEARCH[search]
        STORE[store]
        LEARN[learn]
    end

    subgraph Router[QueryRouter]
        CLASSIFY[IntentClassifier]
        SELECT[Source Selection]
    end

    subgraph Adapters[Source Adapters]
        YAML[YamlAdapter]
        CODE[CodeAdapter]
        SLACK[SlackAdapter]
        JIRA[JiraAdapter]
        GITLAB[GitLabAdapter]
        INSCOPE[InScopeAdapter]
        CALENDAR[CalendarAdapter]
        GMAIL[GmailAdapter]
        GDRIVE[GDriveAdapter]
        GITHUB[GitHubAdapter]
    end

    subgraph Output[Result Processing]
        MERGER[ResultMerger]
        FORMATTER[ResultFormatter]
    end

    Interface --> Router
    Router --> Adapters
    Adapters --> Output
```

## Class Architecture

```mermaid
classDiagram
    class MemoryInterface {
        +router: QueryRouter
        +merger: ResultMerger
        +formatter: ResultFormatter
        +executor: ParallelExecutor
        +query(question, sources): QueryResult
        +search(query, sources): QueryResult
        +store(key, value, source): bool
        +learn(learning, task): bool
        +health(): dict
    }

    class QueryRouter {
        +classifier: IntentClassifier
        +route(question, sources): list[AdapterInfo]
    }

    class IntentClassifier {
        +classify(question): IntentClassification
    }

    class SourceAdapter {
        <<protocol>>
        +query(question, filter): AdapterResult
        +search(query, filter): AdapterResult
        +health(): HealthStatus
    }

    class BaseAdapter {
        +name: str
        +display_name: str
        +capabilities: set
    }

    class ResultMerger {
        +merge(results): list[MemoryItem]
        +deduplicate(items): list[MemoryItem]
        +rank(items): list[MemoryItem]
    }

    class ResultFormatter {
        +format(result): str
        +to_markdown(result): str
    }

    MemoryInterface --> QueryRouter
    MemoryInterface --> ResultMerger
    MemoryInterface --> ResultFormatter
    QueryRouter --> IntentClassifier
    BaseAdapter ..|> SourceAdapter
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| MemoryInterface | `services/memory_abstraction/interface.py` | Main entry point |
| QueryRouter | `services/memory_abstraction/router.py` | Route queries to adapters |
| IntentClassifier | `services/memory_abstraction/classifier.py` | Classify query intent |
| ResultMerger | `services/memory_abstraction/merger.py` | Combine adapter results |
| ResultFormatter | `services/memory_abstraction/formatter.py` | Format for LLM output |
| SourceAdapter | `services/memory_abstraction/adapter_protocol.py` | Adapter protocol |
| AdapterRegistry | `services/memory_abstraction/registry.py` | Adapter discovery |
| Models | `services/memory_abstraction/models.py` | Data models |

## Data Models

```mermaid
classDiagram
    class MemoryItem {
        +id: str
        +source: str
        +content: str
        +metadata: dict
        +relevance: float
        +timestamp: datetime
    }

    class QueryResult {
        +query_id: str
        +question: str
        +intent: IntentClassification
        +items: list[MemoryItem]
        +sources_queried: list[str]
        +duration_ms: float
        +to_markdown(): str
    }

    class IntentClassification {
        +intent: str
        +confidence: float
        +suggested_sources: list[str]
        +keywords: list[str]
    }

    class AdapterResult {
        +source: str
        +items: list[MemoryItem]
        +success: bool
        +error: str
        +duration_ms: float
    }

    class SourceFilter {
        +name: str
        +limit: int
        +project: str
        +persona: str
    }

    class HealthStatus {
        +healthy: bool
        +latency_ms: float
        +error: str
    }

    QueryResult --> MemoryItem
    QueryResult --> IntentClassification
    AdapterResult --> MemoryItem
```

## Adapter Registration

Use the `@memory_adapter` decorator:

```python
from services.memory_abstraction import memory_adapter, BaseAdapter

@memory_adapter(
    name="my_source",
    display_name="My Source",
    capabilities={"query", "search"},
    intent_keywords=["my", "custom", "source"],
    latency_class="fast",  # or "slow"
)
class MySourceAdapter(BaseAdapter):
    async def query(self, question: str, filter: SourceFilter) -> AdapterResult:
        # Implement query logic
        return AdapterResult(
            source=self.name,
            items=[...],
            success=True
        )

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=True, latency_ms=10.0)
```

## Usage Examples

```python
from services.memory_abstraction import MemoryInterface, SourceFilter

memory = MemoryInterface()

# Auto-route based on intent
result = await memory.query("What am I working on?")
# → Routes to YAML adapter (state/current_work)

result = await memory.query("Show billing code")
# → Routes to Code adapter (vector search)

result = await memory.query("How do I configure RDS?")
# → Routes to InScope adapter (slow, external)

# Query specific sources
result = await memory.query(
    "Find authentication code",
    sources=[
        SourceFilter(name="code", project="backend"),
        SourceFilter(name="gitlab", limit=5),
    ]
)

# Get markdown output for LLM
print(result.to_markdown())
```

## Latency Classes

| Class | Latency | Sources | Bootstrap |
|-------|---------|---------|-----------|
| **fast** | <2s | yaml, code, slack | Used in session startup |
| **slow** | >2s | jira, gitlab, inscope, calendar, gmail, gdrive | Explicit request only |

```python
# Query fast sources only (default)
result = await memory.query("What am I working on?")

# Include slow sources
result = await memory.query(
    "How do I configure RDS?",
    include_slow=True
)
```

## Intent Classification

The classifier maps questions to sources:

| Intent | Keywords | Sources |
|--------|----------|---------|
| `current_work` | "working on", "current", "active" | yaml |
| `code_search` | "where", "find", "code", "function" | code |
| `documentation` | "how", "configure", "RDS", "Clowder" | inscope |
| `communication` | "said", "discuss", "slack" | slack |
| `calendar` | "meeting", "schedule", "calendar" | calendar |
| `email` | "email", "gmail", "inbox" | gmail |

## Related Diagrams

- [Memory Architecture](./memory-architecture.md)
- [Unified Memory Query](./unified-memory-query.md)
- [Memory Operations](./memory-operations.md)
- [Session Bootstrap](../08-data-flows/session-bootstrap.md)
