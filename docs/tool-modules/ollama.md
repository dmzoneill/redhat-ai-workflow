# 🧠 Ollama Module (aa_ollama)

Local LLM inference using Ollama with support for NPU, iGPU, NVIDIA, and CPU backends.

## Overview

The Ollama module provides:
- **Local inference**: Run LLMs without cloud dependencies
- **Multiple backends**: NPU, iGPU, NVIDIA GPU, or CPU
- **Context enrichment**: Enhance prompts with local knowledge
- **Embedding generation**: Local embeddings for vector search

## Architecture

```mermaid
graph TB
    subgraph Input["Input"]
        PROMPT[User Prompt]
        CONTEXT[Context Data]
    end

    subgraph Enrichment["Context Enrichment"]
        KNOWLEDGE[Project Knowledge]
        MEMORY[Memory State]
        CODE[Code Search]
    end

    subgraph Backend["Inference Backend"]
        NPU[Intel NPU<br/>Ultra low power]
        IGPU[Intel iGPU<br/>Balanced]
        NVIDIA[NVIDIA GPU<br/>High performance]
        CPU[CPU<br/>Fallback]
    end

    subgraph Output["Output"]
        RESPONSE[LLM Response]
    end

    PROMPT --> KNOWLEDGE
    CONTEXT --> KNOWLEDGE
    KNOWLEDGE --> MEMORY
    MEMORY --> CODE

    CODE --> NPU
    CODE --> IGPU
    CODE --> NVIDIA
    CODE --> CPU

    NPU --> RESPONSE
    IGPU --> RESPONSE
    NVIDIA --> RESPONSE
    CPU --> RESPONSE

    style NPU fill:#10b981,stroke:#059669,color:#fff
    style IGPU fill:#6366f1,stroke:#4f46e5,color:#fff
    style NVIDIA fill:#f59e0b,stroke:#d97706,color:#fff
```

## Backend Selection

```mermaid
flowchart TD
    A[Inference Request] --> B{Check Available Backends}

    B --> C{NVIDIA GPU?}
    C -->|Available| D[Use NVIDIA]
    C -->|No| E{Intel NPU?}

    E -->|Available| F[Use NPU]
    E -->|No| G{Intel iGPU?}

    G -->|Available| H[Use iGPU]
    G -->|No| I[Use CPU]

    D --> J[Run Inference]
    F --> J
    H --> J
    I --> J
```

### Backend Comparison

| Backend | Speed | Power | Memory | Best For |
|---------|-------|-------|--------|----------|
| **NVIDIA GPU** | Fastest | High | 8GB+ VRAM | Large models, batch processing |
| **Intel NPU** | Fast | Ultra Low | Shared | Always-on, small models |
| **Intel iGPU** | Medium | Low | Shared | Balanced workloads |
| **CPU** | Slowest | Medium | RAM | Fallback, any model |

## Tools

### Inference

| Tool | Description |
|------|-------------|
| `ollama_generate` | Generate text completion |
| `ollama_chat` | Chat-style conversation |
| `ollama_embed` | Generate embeddings |

### Backend Management

| Tool | Description |
|------|-------------|
| `ollama_list_models` | List available models |
| `ollama_pull_model` | Download a model |
| `ollama_backend_status` | Check backend availability |

### Context Enrichment

| Tool | Description |
|------|-------------|
| `ollama_enrich_context` | Enrich prompt with context |
| `ollama_classify` | Classify text using local model |

## Context Enrichment

The context enrichment pipeline adds relevant information to prompts:

```mermaid
sequenceDiagram
    participant User
    participant Tool as ollama_generate
    participant Enricher as Context Enricher
    participant KB as Knowledge Base
    participant Code as Code Search
    participant LLM as Ollama

    User->>Tool: Generate with prompt
    Tool->>Enricher: Enrich context

    par Gather context
        Enricher->>KB: Get project knowledge
        Enricher->>Code: Search relevant code
    end

    KB-->>Enricher: Architecture, patterns
    Code-->>Enricher: Related code snippets

    Enricher->>Enricher: Build enriched prompt
    Enricher->>LLM: Generate with context
    LLM-->>User: Enriched response
```

### Enrichment Layers

```mermaid
graph TB
    subgraph Layer1["Layer 1: Project Knowledge"]
        ARCH[Architecture Overview]
        PATTERNS[Coding Patterns]
        GOTCHAS[Known Gotchas]
    end

    subgraph Layer2["Layer 2: Memory State"]
        CURRENT[Current Work]
        RECENT[Recent Actions]
        FIXES[Known Fixes]
    end

    subgraph Layer3["Layer 3: Code Context"]
        SEMANTIC[Semantic Search]
        RELATED[Related Files]
        DEPS[Dependencies]
    end

    subgraph Prompt["Enriched Prompt"]
        FINAL[Final Prompt]
    end

    ARCH --> FINAL
    PATTERNS --> FINAL
    GOTCHAS --> FINAL

    CURRENT --> FINAL
    RECENT --> FINAL
    FIXES --> FINAL

    SEMANTIC --> FINAL
    RELATED --> FINAL
    DEPS --> FINAL
```

## Configuration

### config.json Settings

```json
{
  "ollama": {
    "base_url": "http://localhost:11434",
    "default_model": "llama3.2:8b",
    "backend_priority": ["nvidia", "npu", "igpu", "cpu"],
    "context_enrichment": {
      "enabled": true,
      "include_knowledge": true,
      "include_code_search": true,
      "max_context_tokens": 4096
    }
  }
}
```

### NPU Configuration

For Intel NPU acceleration (Meteor Lake and newer):

```bash
# Check NPU availability
$ cat /sys/class/accel/accel0/device/description
Intel(R) AI Boost

# Set environment for NPU
export OLLAMA_NPU_ENABLED=1
export OLLAMA_NPU_DEVICE=/dev/accel/accel0
```

## Model Management

### Available Models

```mermaid
graph LR
    subgraph Small["Small (< 4GB)"]
        LLAMA3_2[llama3.2:3b]
        PHI3[phi3:mini]
        GEMMA2[gemma2:2b]
    end

    subgraph Medium["Medium (4-8GB)"]
        LLAMA3_8B[llama3.2:8b]
        MISTRAL[mistral:7b]
        CODELLAMA[codellama:7b]
    end

    subgraph Large["Large (> 8GB)"]
        LLAMA3_70B[llama3:70b]
        MIXTRAL[mixtral:8x7b]
    end

    subgraph NPU["NPU Optimized"]
        NPU_SMALL[Small models only]
    end

    Small --> NPU
```

### Model Selection by Task

| Task | Recommended Model | Backend |
|------|-------------------|---------|
| Code completion | codellama:7b | GPU/iGPU |
| Documentation | llama3.2:8b | GPU/iGPU |
| Classification | phi3:mini | NPU/CPU |
| Embedding | nomic-embed-text | Any |
| Chat | mistral:7b | GPU/iGPU |

## Usage Examples

### Basic Generation

```python
# Simple completion
ollama_generate(prompt="Explain this error: {error_message}")

# With model selection
ollama_generate(
    prompt="Review this code",
    model="codellama:7b"
)
```

### With Context Enrichment

```python
# Automatic enrichment
ollama_enrich_context(
    prompt="How should I implement caching?",
    project="automation-analytics-backend",
    include_code=True
)
```

### Embedding Generation

```python
# Generate embeddings for text
ollama_embed(
    text="Calculate vCPU billing hours",
    model="nomic-embed-text"
)
```

## Performance Optimization

### Response Caching

```mermaid
flowchart TD
    A[Generation Request] --> B{Cache Check}
    B -->|Hit| C[Return Cached]
    B -->|Miss| D[Run Inference]
    D --> E[Cache Response]
    E --> F[Return Response]
    C --> F
```

### Batch Processing

```mermaid
sequenceDiagram
    participant Client
    participant Queue as Request Queue
    participant Batcher as Batch Processor
    participant LLM as Ollama

    Client->>Queue: Request 1
    Client->>Queue: Request 2
    Client->>Queue: Request 3

    Note over Queue: Wait for batch or timeout

    Queue->>Batcher: Batch of 3 requests
    Batcher->>LLM: Parallel inference
    LLM-->>Batcher: Batch responses
    Batcher-->>Client: Individual responses
```

## Error Handling

### Backend Fallback

```mermaid
flowchart TD
    A[Inference Request] --> B{Primary Backend}
    B -->|Success| C[Return Response]
    B -->|Failure| D{Fallback Backend}
    D -->|Success| C
    D -->|Failure| E{CPU Fallback}
    E -->|Success| C
    E -->|Failure| F[Error: No backends available]
```

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Connection refused` | Ollama not running | Start ollama service |
| `Model not found` | Model not pulled | Run `ollama pull <model>` |
| `Out of memory` | Model too large | Use smaller model or increase memory |
| `NPU not available` | Missing driver | Install Intel NPU driver |

## Dependencies

### System Requirements

- **Ollama**: Local LLM runtime (required)
- **Intel NPU Driver**: For NPU acceleration (optional)
- **CUDA**: For NVIDIA GPU acceleration (optional)

### Python Packages

- **httpx**: Async HTTP client for Ollama API
- **numpy**: For embedding operations

## See Also

- [Code Search Module](./code_search.md)
- [Knowledge Module](./knowledge.md)
- [Vector Search Architecture](../architecture/vector-search.md)
