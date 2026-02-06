"""
AA Memory YAML - YAML-based memory storage adapter.

This module provides a memory adapter for the YAML-based memory system,
exposing state, learned patterns, and knowledge as a memory source.

Exports:
- YamlMemoryAdapter: Memory adapter for YAML files
"""

from .adapter import YamlMemoryAdapter

__all__ = ["YamlMemoryAdapter"]
