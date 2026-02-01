#!/usr/bin/env python3
"""Entry point for running stats service as a module."""

import asyncio

from services.stats.daemon import main

if __name__ == "__main__":
    asyncio.run(main())
