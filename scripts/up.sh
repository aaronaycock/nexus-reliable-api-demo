#!/usr/bin/env bash
# Start everything: dev server, endpoints, two stand-in services, three workers, gateway.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$REPO"
mkdir -p .run

if ! "$TEMPORAL" operator namespace describe -n api-callers >/dev/null 2>&1; then
  echo "starting Temporal dev server (UI http://localhost:8233)"
  # nexusoperation.enableStandalone turns on Standalone Nexus Operations (pre-release).
  # On Temporal Cloud this is a per-namespace enablement instead.
  nohup "$TEMPORAL" server start-dev \
    --namespace api-callers --namespace notifications --namespace task-center --namespace billing \
    --dynamic-config-value nexusoperation.enableStandalone=true \
    --http-port 7243 --log-level warn > .run/temporal.log 2>&1 &
  echo $! > .run/temporal.pid
  for _ in $(seq 1 60); do
    "$TEMPORAL" operator namespace describe -n billing >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

endpoint() {  # name, target namespace, target task queue
  "$TEMPORAL" operator nexus endpoint get --name "$1" >/dev/null 2>&1 ||
    "$TEMPORAL" operator nexus endpoint create --name "$1" --target-namespace "$2" --target-task-queue "$3"
}
STAMP="${NEXUS_ENV:-dev}"   # e.g. NEXUS_ENV=prod-ch make up: endpoints notifications-prod-ch, task-center-prod-ch
endpoint "notifications-$STAMP" notifications notifications-nexus
endpoint "task-center-$STAMP" task-center task-center-nexus

echo "web UI:  http://localhost:8000    (Ctrl-C stops the apps; 'make down' stops Temporal)"
exec .venv/bin/honcho start --env /dev/null  # local defaults only; never pick up a stray .env
