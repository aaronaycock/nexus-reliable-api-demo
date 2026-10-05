"""What the gateway exposes, built from the Nexus contracts in contracts/.

Adding an operation to a contract and an example here is all it takes for the
gateway and the web UI to offer it.
"""

from pathlib import Path

import yaml

from common import config

CONTRACTS = Path(__file__).parent.parent / "contracts"

# Which endpoint fronts each service in this environment.
ENDPOINTS = {
    "notifications.v1": config.NOTIFY_ENDPOINT,
    "task-center.v1": config.TASKS_ENDPOINT,
}

# How long Temporal keeps trying before the operation times out.
TIMEOUTS_S = {
    ("notifications.v1", "send"): 60 * 60,
    ("task-center.v1", "request_input"): 7 * 24 * 60 * 60,
}

EXAMPLES = {
    ("notifications.v1", "send"): {
        "recipient": "dana",
        "channel": "email",
        "template": "task_assigned",
        "subject": "Quarterly review is ready",
        "reference": "review-q3",
    },
    ("task-center.v1", "request_input"): {
        "reference": "release-2026-10-05",
        "requested_by": "ci",
        "assignee": "dana",
        "kind": "approve_reject",
        "title": "Approve production release 2026-10-05",
        "due_in_seconds": 3600,
    },
}


def _load() -> list[dict]:
    entries = []
    for path in sorted(CONTRACTS.glob("*.nexusrpc.yaml")):
        spec = yaml.safe_load(path.read_text())
        for svc in spec["services"].values():
            service = svc["fqn"]  # wire names, as callers use them
            for op in svc["operations"].values():
                operation = op["fqn"]
                entries.append({
                    "endpoint": ENDPOINTS[service],
                    "service": service,
                    "operation": operation,
                    "description": op.get("description", "").strip(),
                    "timeout_s": TIMEOUTS_S.get((service, operation), 60 * 60),
                    "example": EXAMPLES.get((service, operation), {}),
                })
    return entries


CATALOG = _load()


def find(endpoint: str, service: str, operation: str) -> dict | None:
    return next((e for e in CATALOG
                 if (e["endpoint"], e["service"], e["operation"]) == (endpoint, service, operation)), None)
