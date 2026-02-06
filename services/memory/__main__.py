#!/usr/bin/env python3
"""Entry point for running memory service as a module."""

from services.memory.daemon import MemoryDaemon

if __name__ == "__main__":
    MemoryDaemon.main()
