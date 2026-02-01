#!/usr/bin/env python3
"""Entry point for running video service as a module."""

import asyncio

from services.video.daemon import main

if __name__ == "__main__":
    asyncio.run(main())
