#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ -x ".venv/bin/mypy" ]]; then
  exec ".venv/bin/mypy" --strict src/pullbox/
fi

exec python -m mypy --strict src/pullbox/
