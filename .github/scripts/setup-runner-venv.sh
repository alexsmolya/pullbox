#!/usr/bin/env bash
# Build or reuse a persistent venv scoped to the current runner, Python version,
# and extras set. Requires actions/setup-python to have already selected Python.

set -euo pipefail

EXTRAS="${1:?extras required}"
PACKAGING_TOOLS_VERSION=("pip>=26.0" "wheel")
RUNNER_SLUG="$(printf '%s' "${RUNNER_NAME:-unknown-runner}" | tr ' /:' '---')"
PYTHON_VERSION="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
HASH_INPUT="$(cat pyproject.toml .github/scripts/setup-runner-venv.sh):::${PYTHON_VERSION}:::${EXTRAS}:::${PACKAGING_TOOLS_VERSION[*]}"
if command -v sha256sum >/dev/null 2>&1; then
  HASH="$(printf '%s' "$HASH_INPUT" | sha256sum | cut -c1-16)"
else
  HASH="$(printf '%s' "$HASH_INPUT" | shasum -a 256 | cut -c1-16)"
fi

if [ -n "${PULLBOX_RUNNER_VENV_ROOT:-}" ]; then
  BASE_VENV_ROOT="${PULLBOX_RUNNER_VENV_ROOT}"
elif [ -d "/opt/github-runner" ] && [ -w "/opt/github-runner" ]; then
  BASE_VENV_ROOT="/opt/github-runner/venvs"
elif [ -n "${RUNNER_TEMP:-}" ]; then
  BASE_VENV_ROOT="${RUNNER_TEMP}/pullbox-venvs"
else
  BASE_VENV_ROOT="${TMPDIR:-/tmp}/pullbox-venvs"
fi

VENV_ROOT="${BASE_VENV_ROOT}/${RUNNER_SLUG}"
VENV_PATH="${VENV_ROOT}/pullbox-py${PYTHON_VERSION}-${EXTRAS//,/_}-${HASH}"
LOCK_DIR="${VENV_PATH}.lock"

mkdir -p "$VENV_ROOT"

touch_last_used() {
  mkdir -p "$VENV_PATH"
  touch "$VENV_PATH/.last_used"
}

venv_is_healthy() {
  [ -x "$VENV_PATH/bin/python" ] &&
    [ -f "$VENV_PATH/.ready" ] &&
    "$VENV_PATH/bin/python" -c 'import sys; print(sys.executable)' >/dev/null 2>&1 &&
    "$VENV_PATH/bin/pip" --version >/dev/null 2>&1
}

if venv_is_healthy; then
  echo "Using cached runner-local venv: $VENV_PATH"
  "$VENV_PATH/bin/python" -m pip install --upgrade "${PACKAGING_TOOLS_VERSION[@]}"
  touch_last_used
else
  while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    sleep 2
  done
  trap 'rm -rf "$LOCK_DIR"' EXIT

  if ! venv_is_healthy; then
    echo "Building runner-local venv: $VENV_PATH"
    rm -rf "$VENV_PATH"
    python -m venv "$VENV_PATH"
    "$VENV_PATH/bin/python" -m pip install --upgrade "${PACKAGING_TOOLS_VERSION[@]}"
    "$VENV_PATH/bin/python" -m pip install -e ".[${EXTRAS}]"
    touch "$VENV_PATH/.ready"
    touch "$VENV_PATH/.last_used"
  fi

  touch_last_used
fi

export VENV_PATH
export PATH="$VENV_PATH/bin:$PATH"

if [ -n "${GITHUB_ENV:-}" ]; then
  echo "VENV_PATH=$VENV_PATH" >> "$GITHUB_ENV"
  echo "PATH=$VENV_PATH/bin:$PATH" >> "$GITHUB_ENV"
fi

if [ -n "${GITHUB_PATH:-}" ]; then
  echo "$VENV_PATH/bin" >> "$GITHUB_PATH"
fi
