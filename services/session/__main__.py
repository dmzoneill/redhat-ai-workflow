#!/usr/bin/env python3
"""Entry point for running session service as a module."""

from services.session.daemon import SessionDaemon

if __name__ == "__main__":
    SessionDaemon.main()
