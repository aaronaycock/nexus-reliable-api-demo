notification-api: .venv/bin/uvicorn services.notification_api.app:app --port 8001 --log-level warning
task-center: .venv/bin/uvicorn services.task_center.app:app --port 8002 --log-level warning
notify-worker: .venv/bin/python -m handlers.notifications.worker
tasks-worker: .venv/bin/python -m handlers.task_center.worker
billing-worker: .venv/bin/python -m teams.billing.worker
gateway: .venv/bin/uvicorn gateway.app:app --port 8000 --log-level warning
