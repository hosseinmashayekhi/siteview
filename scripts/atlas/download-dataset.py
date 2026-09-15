#!/usr/bin/env python3
"""Compatibility entry point for the frozen Atlas dataset downloader."""

import sys

from atlas.cli import app


if __name__ == "__main__":
    app(args=["download-dataset", *sys.argv[1:]], prog_name="download-dataset")
