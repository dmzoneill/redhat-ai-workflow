#!/usr/bin/env python3
"""Entry point for running meet service as a module."""

import asyncio

from services.meet.daemon import main

if __name__ == "__main__":
    asyncio.run(main())
