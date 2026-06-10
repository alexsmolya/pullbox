#!/bin/bash
# Pullbox launcher with restart support.
# Detects exit code 42 (restart requested) and relaunches.
#
# Usage:
#   ./scripts/pullbox.sh
#   PULLBOX_DATA_DIR=/path/to/data ./scripts/pullbox.sh

set -euo pipefail

RESTART_EXIT_CODE=42
PULLBOX_DIR="${PULLBOX_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

cd "$PULLBOX_DIR"

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

while true; do
    python -m pullbox "$@"
    exit_code=$?
    if [ $exit_code -eq $RESTART_EXIT_CODE ]; then
        echo "Restart requested, relaunching..."
        continue
    fi
    exit $exit_code
done
