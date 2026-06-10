#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: run_with_timeout.py <seconds> <command> [arg...]", file=sys.stderr)
        return 2

    try:
        timeout_seconds = float(sys.argv[1])
    except ValueError:
        print(f"Invalid timeout: {sys.argv[1]}", file=sys.stderr)
        return 2

    command = sys.argv[2:]
    try:
        completed = subprocess.run(command, check=False, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        print(f"Command timed out after {timeout_seconds:g} seconds", file=sys.stderr)
        return 124

    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
