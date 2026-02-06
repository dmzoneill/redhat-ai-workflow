#!/usr/bin/env python3
"""Entry point for running sprint service as a module."""

from services.sprint.daemon import SprintDaemon

if __name__ == "__main__":
    SprintDaemon.main()
