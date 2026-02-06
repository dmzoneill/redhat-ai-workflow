# Ollama Tools

> aa_ollama module for local LLM inference

## Diagram

```mermaid
classDiagram
    class OllamaBasic {
        +ollama_list_models(): list
        +ollama_generate(model, prompt): str
        +ollama_chat(model, messages): str
        +ollama_embeddings(model, text): list
        +ollama_model_info(model): dict
    }

    class OllamaClient {
        +base_url: str
        +generate(model, prompt, options): str
        +chat(model, messages, options): str
        +embeddings(model, input): list
        +list(): list
        +show(model): dict
    }

    class ToolFilter {
        +filter_tools(tools, query): list
        +rank_tools(tools, context): list
        +get_relevant_tools(intent): list
    }

    class ContextEnrichment {
        +enrich_prompt(prompt, context): str
        +get_relevant_context(query): dict
        +summarize_context(context): str
    }

    OllamaBasic --> OllamaClient
    OllamaBasic --> ToolFilter
    OllamaBasic --> ContextEnrichment
```

## Inference Flow

```mermaid
sequenceDiagram
    participant Tool as Ollama Tool
    participant Client as Ollama Client
    participant Server as Ollama Server
    participant Model as LLM Model

    Tool->>Client: generate(model, prompt)
    Client->>Server: POST /api/generate
    Server->>Model: Load model (if needed)
    Model-->>Server: Model ready
    
    loop Streaming response
        Server->>Client: Token chunk
        Client->>Tool: Accumulated text
    end

    Server-->>Client: Final response
    Client-->>Tool: Complete response
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_ollama/src/` | Ollama operations |
| client.py | `tool_modules/aa_ollama/src/` | HTTP client |
| tool_filter.py | `tool_modules/aa_ollama/src/` | Tool filtering |
| context_enrichment.py | `tool_modules/aa_ollama/src/` | Context building |
| cache.py | `tool_modules/aa_ollama/src/` | Response caching |
| categories.py | `tool_modules/aa_ollama/src/` | Tool categorization |

## Tool Summary

| Tool | Description |
|------|-------------|
| `ollama_list_models` | List available models |
| `ollama_generate` | Generate text completion |
| `ollama_chat` | Chat completion |
| `ollama_embeddings` | Generate embeddings |
| `ollama_model_info` | Get model details |

## Tool Filtering

```mermaid
flowchart TB
    subgraph Input[Input]
        QUERY[User Query]
        ALL_TOOLS[All Available Tools]
    end

    subgraph Filter[Filtering Process]
        EMBED[Generate Embeddings]
        SIMILARITY[Compute Similarity]
        RANK[Rank Tools]
        SELECT[Select Top K]
    end

    subgraph Output[Output]
        FILTERED[Filtered Tools]
        CONTEXT[Tool Context]
    end

    QUERY --> EMBED
    ALL_TOOLS --> EMBED
    EMBED --> SIMILARITY
    SIMILARITY --> RANK
    RANK --> SELECT
    SELECT --> FILTERED
    FILTERED --> CONTEXT
```

## Configuration

```json
{
  "ollama": {
    "base_url": "http://localhost:11434",
    "default_model": "llama3.2",
    "embedding_model": "nomic-embed-text",
    "timeout": 120,
    "options": {
      "temperature": 0.7,
      "num_ctx": 4096
    }
  }
}
```

## Model Selection

| Model | Use Case | Size |
|-------|----------|------|
| llama3.2 | General tasks | 3B |
| codellama | Code generation | 7B |
| nomic-embed-text | Embeddings | 137M |
| mistral | Complex reasoning | 7B |

## Caching Strategy

```mermaid
flowchart TB
    subgraph Cache[Response Cache]
        HASH[Query Hash]
        STORE[Cache Store]
        TTL[TTL Check]
    end

    subgraph Flow[Cache Flow]
        CHECK{Cache hit?}
        RETURN[Return cached]
        GENERATE[Generate new]
        SAVE[Save to cache]
    end

    HASH --> CHECK
    CHECK -->|Yes| TTL
    TTL -->|Valid| RETURN
    TTL -->|Expired| GENERATE
    CHECK -->|No| GENERATE
    GENERATE --> SAVE
    SAVE --> STORE
```

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Code Search Tools](./code-search-tools.md)
- [Memory Abstraction](../06-memory/memory-abstraction.md)
