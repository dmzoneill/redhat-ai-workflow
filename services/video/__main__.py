#!/usr/bin/env python3
"""Entry point for running video service as a module."""

from services.video.daemon import VideoDaemon

if __name__ == "__main__":
    VideoDaemon.main()
