#!/usr/bin/env bash
# A CI job (GitHub Actions, Jenkins, a shell script) asks a person to approve a
# release, using nothing but HTTP. It waits briefly, gets a status URL, and
# polls it until the person answers. Exit 0 if approved, 1 otherwise.
#
#   RELEASE=2026-10-05 APPROVER=dana scripts/ci_approval.sh
set -euo pipefail
GATEWAY="${GATEWAY_URL:-http://localhost:8000}"
RELEASE="${RELEASE:-$(date +%Y-%m-%d-%H%M)}"
APPROVER="${APPROVER:-dana}"
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(d$1)"; }

echo "Requesting approval for release $RELEASE from $APPROVER..."
resp=$(curl -sS -X POST "$GATEWAY/task-center-${NEXUS_ENV:-dev}/task-center.v1/request_input?wait_s=2" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: release-$RELEASE" \
  -d "{\"reference\": \"release-$RELEASE\", \"requested_by\": \"ci\", \"assignee\": \"$APPROVER\",
       \"kind\": \"approve_reject\", \"title\": \"Approve production release $RELEASE\", \"due_in_seconds\": 3600}")
status_url=$(echo "$resp" | json "['status_url']")
echo "Waiting on a person. Status: $GATEWAY$status_url  (approve it in the web UI)"

while true; do
  op=$(curl -sS "$GATEWAY$status_url")
  status=$(echo "$op" | json "['status']")
  [ "$status" != "RUNNING" ] && break
  sleep 3
done

outcome=$(echo "$op" | json ".get('result', {}).get('outcome', '$status')")
who=$(echo "$op" | json ".get('result', {}).get('responded_by') or ''")
echo "Release $RELEASE: $outcome${who:+ by $who}"
[ "$outcome" = "approved" ]
