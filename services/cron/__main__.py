#!/usr/bin/env python3
"""Entry point for running cron service as a module."""

from services.cron.daemon import main

if __name__ == "__main__":
    main()
