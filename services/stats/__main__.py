#!/usr/bin/env python3
"""Entry point for running stats service as a module."""

from services.stats.daemon import StatsDaemon

if __name__ == "__main__":
    StatsDaemon.main()
