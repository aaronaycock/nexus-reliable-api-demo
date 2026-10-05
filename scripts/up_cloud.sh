#!/usr/bin/env bash
# Same processes as 'make up', pointed at Temporal Cloud. No dev server.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$REPO"
[ -f cloud.env ] || { echo "copy config/cloud.env.example to cloud.env and fill it in first" >&2; exit 1; }
set -a; source cloud.env; set +a
echo "web UI:  http://localhost:8000    caller namespace: $CALLER_NAMESPACE"
exec .venv/bin/honcho start --env /dev/null  # settings come from cloud.env above
