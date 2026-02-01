#!/usr/bin/env python3
"""Entry point for running extension_watcher service as a module."""

from services.extension_watcher.daemon import main

if __name__ == "__main__":
    main()
