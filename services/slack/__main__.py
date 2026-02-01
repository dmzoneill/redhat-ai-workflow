#!/usr/bin/env python3
"""Entry point for running slack service as a module."""

import asyncio

from services.slack.daemon import main

if __name__ == "__main__":
    asyncio.run(main())
