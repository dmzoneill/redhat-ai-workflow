# Adapter Pattern

> Memory adapter protocol for unified data access

## Diagram

```mermaid
classDiagram
    class MemoryAdapterProtocol {
        <<protocol>>
        +name: str
        +latency_class: str
        +query(question): list~Result~
        +search(query): list~Result~
        +health_check(): dict
    }

    class YAMLAdapter {
        +name = "yaml"
        +latency_class = "fast"
        +query(question): list
        +search(query): list
        +read(path): dict
        +write(path, data)
    }

    class JiraAdapter {
        +name = "jira"
        +latency_class = "slow"
        +query(question): list
        +search(query): list
        +get_issue(key): dict
    }

    class GitLabAdapter {
        +name = "gitlab"
        +latency_class = "slow"
        +query(question): list
        +search(query): list
        +get_mr(id): dict
    }

    class SlackAdapter {
        +name = "slack"
        +latency_class = "fast"
        +query(question): list
        +search(query): list
        +search_messages(query): list
    }

    class InScopeAdapter {
        +name = "inscope"
        +latency_class = "slow"
        +query(question): list
        +search(query): list
    }

    class CodeSearchAdapter {
        +name = "code"
        +latency_class = "fast"
        +query(question): list
        +search(query): list
    }

    MemoryAdapterProtocol <|.. YAMLAdapter
    MemoryAdapterProtocol <|.. JiraAdapter
    MemoryAdapterProtocol <|.. GitLabAdapter
    MemoryAdapterProtocol <|.. SlackAdapter
    MemoryAdapterProtocol <|.. InScopeAdapter
    MemoryAdapterProtocol <|.. CodeSearchAdapter
```

## Adapter Discovery

```mermaid
flowchart TB
    subgraph Discovery[Adapter Discovery]
        SCAN[Scan tool_modules]
        FIND[Find adapter.py files]
        LOAD[Load adapter classes]
        REGISTER[Register with interface]
    end

    subgraph Registry[Adapter Registry]
        YAML[yaml adapter]
        JIRA[jira adapter]
        GITLAB[gitlab adapter]
        SLACK[slack adapter]
        CODE[code adapter]
        INSCOPE[inscope adapter]
    end

    subgraph Interface[Memory Interface]
        QUERY[query method]
        ROUTE[Route to adapters]
        MERGE[Merge results]
    end

    SCAN --> FIND
    FIND --> LOAD
    LOAD --> REGISTER

    REGISTER --> YAML
    REGISTER --> JIRA
    REGISTER --> GITLAB
    REGISTER --> SLACK
    REGISTER --> CODE
    REGISTER --> INSCOPE

    QUERY --> ROUTE
    ROUTE --> YAML
    ROUTE --> JIRA
    ROUTE --> GITLAB
    ROUTE --> SLACK
    ROUTE --> CODE
    ROUTE --> INSCOPE
    YAML --> MERGE
    JIRA --> MERGE
    GITLAB --> MERGE
    SLACK --> MERGE
    CODE --> MERGE
    INSCOPE --> MERGE
```

## Query Flow

```mermaid
sequenceDiagram
    participant User as User
    participant Interface as MemoryInterface
    participant Classifier as Intent Classifier
    participant Router as Adapter Router
    participant Adapters as Adapters
    participant Merger as Result Merger

    User->>Interface: memory_ask(question)
    Interface->>Classifier: Classify intent
    Classifier-->>Interface: Intent + suggested sources

    Interface->>Router: Route to adapters
    
    par Query adapters
        Router->>Adapters: yaml.query()
        Router->>Adapters: slack.query()
        Router->>Adapters: code.query()
    end

    Adapters-->>Router: Results
    Router->>Merger: Merge results
    Merger-->>Interface: Merged results
    Interface-->>User: Formatted response
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| MemoryAdapterProtocol | `services/memory_abstraction/adapter_protocol.py` | Protocol definition |
| discovery | `services/memory_abstraction/discovery.py` | Adapter discovery |
| registry | `services/memory_abstraction/registry.py` | Adapter registry |
| router | `services/memory_abstraction/router.py` | Query routing |
| merger | `services/memory_abstraction/merger.py` | Result merging |

## Adapter Implementation

```python
# tool_modules/aa_example/src/adapter.py
from services.memory_abstraction import MemoryAdapterProtocol

class ExampleAdapter(MemoryAdapterProtocol):
    name = "example"
    latency_class = "fast"  # or "slow"

    async def query(self, question: str) -> list:
        """Query this source with natural language."""
        # Implementation
        return results

    async def search(self, query: str) -> list:
        """Search this source with keywords."""
        # Implementation
        return results

    async def health_check(self) -> dict:
        """Check adapter health."""
        return {"healthy": True, "message": "OK"}
```

## Latency Classes

| Class | Sources | Latency | Used In |
|-------|---------|---------|---------|
| fast | yaml, code, slack | <2s | Bootstrap, default |
| slow | jira, gitlab, inscope, calendar | >2s | On-demand |

## Related Diagrams

- [Memory Abstraction](../06-memory/memory-abstraction.md)
- [Memory Query Flow](../06-memory/memory-query-flow.md)
- [Tool Module Structure](./tool-module-structure.md)
