#!/usr/bin/env bash

set -euo pipefail

venv_path="$(mktemp -d /tmp/pullbox-clean-room.XXXXXX)"

cleanup() {
  rm -rf "${venv_path}"
}

trap cleanup EXIT

echo "Using clean-room venv: ${venv_path}"
python -m venv "${venv_path}"

export PATH="${venv_path}/bin:${PATH}"

python -m pip install --upgrade pip wheel
pip install -e ".[dev]"
npm ci

PATH="${venv_path}/bin:${PATH}" .github/scripts/preflight-runner.sh python node

ruff check src/ tests/
ruff format --check src/ tests/
mypy src/pullbox/
PULLBOX_SECRET_KEY=test-ci-key pytest tests/unit/ -n 4 -q
