#!/usr/bin/env python3
"""Entry point for running slack service as a module."""

from services.slack.daemon import SlackDaemon

if __name__ == "__main__":
    SlackDaemon.main()
