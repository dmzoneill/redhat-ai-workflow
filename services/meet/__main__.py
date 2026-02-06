#!/usr/bin/env python3
"""Entry point for running meet service as a module."""

from services.meet.daemon import MeetDaemon

if __name__ == "__main__":
    MeetDaemon.main()
