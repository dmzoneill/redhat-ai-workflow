"""
AA Code Search - Semantic code search with local vector embeddings.

This module provides:
- Local vector embeddings using sentence-transformers (no API calls)
- LanceDB for persistent vector storage (embedded, no server)
- Automatic index updates via file watcher
- Integration with knowledge memory system

Architecture (Hybrid Solution):

    ┌─────────────────────────────────────────────────────────┐
    │                    Your Machine                          │
    │  ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │
    │  │  Code    │───▶│ Embedder │───▶│   Vector DB      │  │
    │  │  Files   │    │ (local)  │    │   (LanceDB)      │  │
    │  └──────────┘    └──────────┘    └──────────────────┘  │
    │       │                                  │              │
    │       │ watchfiles                       ▼              │
    │       ▼                          ┌──────────────────┐  │
    │  ┌──────────┐    ┌──────────┐   │  Semantic Search │  │
    │  │  File    │───▶│  Auto    │   │      Tool        │  │
    │  │ Watcher  │    │ Re-index │   └────────┬─────────┘  │
    │  └──────────┘    └──────────┘            │              │
    │                                          ▼              │
    │  ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │
    │  │ Knowledge│◀───│  Claude  │◀───│    Results       │  │
    │  │  Memory  │    │ Analysis │    │                  │  │
    │  └──────────┘    └──────────┘    └──────────────────┘  │
    └─────────────────────────────────────────────────────────┘

Tools:
- code_index: Index a project's code into vector database
- code_search: Semantic search across indexed code
- code_stats: Get indexing statistics
- code_watch: Start/stop automatic index updates
- code_watch_all: Manage watchers for all projects
- knowledge_deep_scan: Deep scan using vectors + Claude analysis

Auto-Update Features:
- File watcher: Monitors changes, re-indexes after 5s quiet period
- Stale check: Auto-updates on search if index > 1 hour old
"""

from .tools_basic import register_tools

__all__ = ["register_tools"]
