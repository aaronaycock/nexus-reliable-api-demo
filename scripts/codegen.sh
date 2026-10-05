#!/usr/bin/env bash
# Contract-first pipeline:
#   Notification API (FastAPI) -> openapi.json -> notifications.nexusrpc.yaml -> contract (nexgen)
#                                             \-> contracts/facades.yaml      -> handler (gen_facade.py)
#   task-center.nexusrpc.yaml (hand-written)                                  -> contract (nexgen)
# Everything generated is committed, so running the demo needs none of this.
set -euo pipefail
source "$(dirname "$0")/env.sh"; cd "$REPO"
NEXGEN_VERSION=v0.2.5   # pinned: nexgen is pre-release and its output may change

if [ ! -x .tools/nexgen ]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) target=aarch64-apple-darwin ;;
    Darwin-x86_64) target=x86_64-apple-darwin ;;
    Linux-aarch64|Linux-arm64) target=aarch64-unknown-linux-gnu ;;
    Linux-x86_64) target=x86_64-unknown-linux-gnu ;;
    *) echo "download nexgen for your platform from https://github.com/temporalio/nexgen/releases" >&2; exit 1 ;;
  esac
  mkdir -p .tools
  curl -sSL "https://github.com/temporalio/nexgen/releases/download/$NEXGEN_VERSION/nexgen-$NEXGEN_VERSION-$target.tar.gz" | tar xz -C .tools nexgen
fi
.tools/nexgen --version

"$PY" -c "import json; from services.notification_api.app import app; json.dump(app.openapi(), open('contracts/openapi/notification-api.json', 'w'), indent=2)"
echo "exported contracts/openapi/notification-api.json"
"$PY" scripts/openapi_to_nexus.py contracts/openapi/notification-api.json contracts/notifications.nexusrpc.yaml

rm -rf contracts/gen/notifications contracts/gen/task_center
.tools/nexgen python contracts/notifications.nexusrpc.yaml --output contracts/gen/notifications
.tools/nexgen python contracts/task-center.nexusrpc.yaml --output contracts/gen/task_center
echo "generated contracts/gen/notifications and contracts/gen/task_center"

"$PY" scripts/gen_facade.py contracts/facades.yaml
