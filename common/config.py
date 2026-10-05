"""Every name the demo uses, in one place.

Defaults target the local dev server started by `make up`. To run against
Temporal Cloud, set the environment variables in `config/cloud.env.example`;
no code changes are needed.
"""

import os

from temporalio.client import Client
from temporalio.envconfig import ClientConfig


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# Namespaces. Each team owns one; callers never need the handler namespaces.
CALLER_NAMESPACE = _env("CALLER_NAMESPACE", "api-callers")  # standalone operations live here
NOTIFY_NAMESPACE = _env("NOTIFY_NAMESPACE", "notifications")  # Notification team
TASKS_NAMESPACE = _env("TASKS_NAMESPACE", "task-center")  # Task Center team
BILLING_NAMESPACE = _env("BILLING_NAMESPACE", "billing")  # a product team that calls both

# The deployment "stamp": an environment, plus a region once there is more than one,
# e.g. dev, staging-us, prod-us, prod-ch. Endpoint names end with it, so moving a
# caller between environments or regions changes this one setting and nothing else.
NEXUS_ENV = _env("NEXUS_ENV", "dev")

# Nexus endpoints: named for the capability plus the stamp, never the namespace.
NOTIFY_ENDPOINT = _env("NOTIFY_ENDPOINT", f"notifications-{NEXUS_ENV}")
TASKS_ENDPOINT = _env("TASKS_ENDPOINT", f"task-center-{NEXUS_ENV}")

# Task queues that the endpoints target.
NOTIFY_TASK_QUEUE = _env("NOTIFY_TASK_QUEUE", "notifications-nexus")
TASKS_TASK_QUEUE = _env("TASKS_TASK_QUEUE", "task-center-nexus")
BILLING_TASK_QUEUE = _env("BILLING_TASK_QUEUE", "billing")

# The non-Temporal services.
NOTIFICATION_API_URL = _env("NOTIFICATION_API_URL", "http://localhost:8001")
NOTIFICATION_API_KEY = _env("NOTIFICATION_API_KEY", "demo-notify-key")  # held by the handler only
TASK_CENTER_URL = _env("TASK_CENTER_URL", "http://localhost:8002")
GATEWAY_URL = _env("GATEWAY_URL", "http://localhost:8000")
TEMPORAL_UI_URL = _env("TEMPORAL_UI_URL", "http://localhost:8233")


async def connect(namespace: str) -> Client:
    """Connect using the active Temporal environment profile.

    Address, TLS and API key come from TEMPORAL_PROFILE / TEMPORAL_CONFIG_FILE
    (see temporal.toml) or TEMPORAL_ADDRESS / TEMPORAL_API_KEY. The namespace
    is always set by the caller, because this demo talks to several.
    """
    config = ClientConfig.load_client_connect_config()
    config["namespace"] = namespace
    return await Client.connect(**config)
