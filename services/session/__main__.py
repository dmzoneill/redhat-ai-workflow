#!/usr/bin/env python3
"""Entry point for running session service as a module."""

import asyncio

from services.session.daemon import main

if __name__ == "__main__":
    asyncio.run(main())
