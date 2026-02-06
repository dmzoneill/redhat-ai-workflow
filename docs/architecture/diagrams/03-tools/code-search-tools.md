# Code Search Tools

> aa_code_search module for semantic code search

## Diagram

```mermaid
flowchart TB
    subgraph Input[Search Input]
        QUERY[Natural Language Query]
        FILTERS[File Filters]
        SCOPE[Search Scope]
    end

    subgraph Embedding[Embedding Generation]
        QUERY_EMBED[Query Embedding]
        CODE_EMBED[Code Embeddings]
        MODEL[Embedding Model]
    end

    subgraph Search[Vector Search]
        LANCE[LanceDB]
        SIMILARITY[Similarity Search]
        RANKING[Result Ranking]
    end

    subgraph Output[Search Results]
        FILES[Matching Files]
        SNIPPETS[Code Snippets]
        SCORES[Relevance Scores]
    end

    QUERY --> QUERY_EMBED
    MODEL --> QUERY_EMBED
    MODEL --> CODE_EMBED

    QUERY_EMBED --> SIMILARITY
    CODE_EMBED --> LANCE
    LANCE --> SIMILARITY
    FILTERS --> SIMILARITY
    SCOPE --> SIMILARITY

    SIMILARITY --> RANKING
    RANKING --> FILES
    RANKING --> SNIPPETS
    RANKING --> SCORES
```

## Class Structure

```mermaid
classDiagram
    class CodeSearchBasic {
        +code_search(query, limit): list
        +code_search_file(query, file): list
        +code_index_status(): dict
        +code_reindex(path): dict
    }

    class VectorIndex {
        +db: LanceDB
        +table: Table
        +add_documents(docs)
        +search(query, k): list
        +delete(ids)
        +count(): int
    }

    class CodeChunker {
        +chunk_file(path): list
        +chunk_function(code): list
        +chunk_class(code): list
        +get_context(chunk): str
    }

    class EmbeddingModel {
        +model: SentenceTransformer
        +encode(text): ndarray
        +encode_batch(texts): ndarray
    }

    CodeSearchBasic --> VectorIndex
    VectorIndex --> EmbeddingModel
    CodeSearchBasic --> CodeChunker
```

## Indexing Flow

```mermaid
sequenceDiagram
    participant Tool as Code Search Tool
    participant Chunker as Code Chunker
    participant Model as Embedding Model
    participant Index as Vector Index

    Tool->>Tool: Scan codebase
    
    loop For each file
        Tool->>Chunker: chunk_file(path)
        Chunker-->>Tool: Code chunks
        
        loop For each chunk
            Tool->>Model: encode(chunk)
            Model-->>Tool: Embedding vector
            Tool->>Index: add_document(chunk, vector)
        end
    end

    Index->>Index: Build index
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_code_search/src/` | Search operations |
| adapter.py | `tool_modules/aa_code_search/src/` | Memory adapter |

## Tool Summary

| Tool | Description |
|------|-------------|
| `code_search` | Semantic code search |
| `code_search_file` | Search within file |
| `code_index_status` | Get index status |
| `code_reindex` | Rebuild index |

## Chunking Strategy

| Element | Chunk Size | Overlap |
|---------|------------|---------|
| Function | Entire function | None |
| Class | Class + methods | None |
| File | 500 tokens | 50 tokens |
| Comment | With context | None |

## Configuration

```json
{
  "code_search": {
    "index_path": "~/.config/aa-workflow/.lancedb",
    "embedding_model": "nomic-embed-text",
    "chunk_size": 500,
    "chunk_overlap": 50,
    "file_extensions": [".py", ".ts", ".js", ".yaml"],
    "exclude_patterns": ["node_modules", "__pycache__", ".git"]
  }
}
```

## Search Query Examples

```
# Natural language queries
"How does authentication work?"
"Where is the database connection configured?"
"Find error handling for API calls"

# Specific queries
"function that validates JWT tokens"
"class that handles Slack messages"
"YAML schema for skills"
```

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Vector Search](../06-memory/vector-search.md)
- [Ollama Tools](./ollama-tools.md)
