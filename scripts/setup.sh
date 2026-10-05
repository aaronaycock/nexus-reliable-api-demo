#!/usr/bin/env bash
# One-time setup: Python venv and a Temporal CLI new enough for Standalone Nexus Operations (1.9.0+).
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$REPO"

PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
[ -x .venv/bin/python ] || "$PYTHON" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

cli_ok() { "$1" --version 2>/dev/null | awk '{print $3}' | awk -F. '{exit !($1 > 1 || ($1 == 1 && $2 >= 9))}'; }
if cli_ok temporal; then
  echo "using temporal CLI on PATH: $(temporal --version)"
elif cli_ok .tools/temporal; then
  echo "using .tools/temporal: $(.tools/temporal --version)"
else
  os=$(uname -s | tr '[:upper:]' '[:lower:]'); arch=$(uname -m)
  case "$arch" in x86_64) arch=amd64 ;; aarch64) arch=arm64 ;; esac
  mkdir -p .tools
  curl -sSL "https://github.com/temporalio/cli/releases/download/v1.9.1/temporal_cli_1.9.1_${os}_${arch}.tar.gz" | tar xz -C .tools temporal
  echo "downloaded $(.tools/temporal --version) to .tools/"
fi
.venv/bin/pip show temporalio | grep -E '^Version' | sed 's/^/temporalio /'
