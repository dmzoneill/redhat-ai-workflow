#!/usr/bin/env python3
"""Entry point for running config service as a module."""

from services.config.daemon import ConfigDaemon

if __name__ == "__main__":
    ConfigDaemon.main()
