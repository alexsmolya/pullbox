#!/usr/bin/env bash

set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <base|python|node|docker|playwright> [capability...]" >&2
  exit 1
fi

runner_name="${RUNNER_NAME:-unknown-runner}"
runner_os="${RUNNER_OS:-unknown-os}"

echo "═══ Runner Preflight ═══"
echo "Runner: ${runner_name}"
echo "OS: ${runner_os}"
uname -a
echo ""

if command -v df >/dev/null 2>&1; then
  echo "── Disk ──"
  df -h .
  echo ""
fi

if command -v free >/dev/null 2>&1; then
  echo "── Memory ──"
  free -h
  echo ""
fi

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "::error::Required command not found: ${cmd}" >&2
    exit 1
  fi
}

print_first_line() {
  local output
  output="$("$@" 2>&1)"
  printf '%s\n' "${output%%$'\n'*}"
}

for capability in "$@"; do
  case "$capability" in
    base)
      echo "── Base Tooling ──"
      require_cmd git
      git --version
      require_cmd curl
      print_first_line curl --version
      require_cmd tar
      print_first_line tar --version
      if command -v sha256sum >/dev/null 2>&1; then
        print_first_line sha256sum --version
      elif command -v shasum >/dev/null 2>&1; then
        print_first_line shasum --version
      else
        echo "::error::Required checksum command not found: sha256sum or shasum" >&2
        exit 1
      fi
      echo ""
      ;;
    python)
      echo "── Python ──"
      require_cmd python
      python --version
      require_cmd pip
      pip --version
      echo ""
      ;;
    node)
      echo "── Node ──"
      require_cmd node
      node --version
      require_cmd npm
      npm --version
      echo ""
      ;;
    docker)
      echo "── Docker ──"
      require_cmd docker
      docker --version
      docker info >/dev/null
      echo "Docker daemon reachable"
      echo ""
      ;;
    playwright)
      echo "── Playwright ──"
      require_cmd playwright
      playwright --version
      echo "PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-<unset>}"
      echo ""
      ;;
    *)
      echo "::error::Unknown preflight capability: ${capability}" >&2
      exit 1
      ;;
  esac
done

echo "Runner preflight passed."
