#!/usr/bin/env bash
# Stop the dev server started by up.sh. Its state is in memory, so the next 'make up' starts clean.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$REPO"
if [ -f .run/temporal.pid ]; then
  kill "$(cat .run/temporal.pid)" 2>/dev/null && echo "stopped Temporal dev server" || true
  rm -f .run/temporal.pid
fi
