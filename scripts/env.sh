# Sourced by every script. Keeps the demo on its own Temporal profile and venv.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
export TEMPORAL_CONFIG_FILE="${TEMPORAL_CONFIG_FILE:-$REPO/temporal.toml}"
export PYTHONPATH="$REPO"
export PYTHONUNBUFFERED=1
if [ -x "$REPO/.tools/temporal" ]; then TEMPORAL="$REPO/.tools/temporal"; else TEMPORAL="temporal"; fi
PY="$REPO/.venv/bin/python"
