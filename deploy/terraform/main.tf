# Example: the demo's namespaces and Nexus endpoints on Temporal Cloud.
# Not applied as part of this repo; adapt names, regions and retention.
# Standalone Nexus Operations are pre-release and enabled per caller namespace
# by Temporal; that step is not in Terraform.

terraform {
  required_providers {
    temporalcloud = { source = "temporalio/temporalcloud" }
  }
}

locals {
  region = "aws-us-east-1"
}

resource "temporalcloud_namespace" "callers" {
  name           = "nexus-demo-callers"
  regions        = [local.region]
  api_key_auth   = true
  retention_days = 3
}

resource "temporalcloud_namespace" "notification" {
  name           = "nexus-demo-notification"
  regions        = [local.region]
  api_key_auth   = true
  retention_days = 3
}

resource "temporalcloud_namespace" "tasks" {
  name           = "nexus-demo-tasks"
  regions        = [local.region]
  api_key_auth   = true
  retention_days = 3
}

# Endpoint names: capability + environment. Callers only ever see these.
resource "temporalcloud_nexus_endpoint" "notifications_dev" {
  name        = "notifications-dev"
  description = "notifications.v1: send. Owned by the Notification team."
  worker_target = {
    namespace_id = temporalcloud_namespace.notification.id
    task_queue   = "notifications-nexus"
  }
  # Every namespace that calls it: callers using standalone operations, and
  # namespaces whose workflows call it (here, none yet: the demo's Task Center
  # notifies from its service, which uses the caller namespace).
  allowed_caller_namespaces = [
    temporalcloud_namespace.callers.id,
  ]
}

resource "temporalcloud_nexus_endpoint" "task_center_dev" {
  name        = "task-center-dev"
  description = "task-center.v1: request_input. Owned by the Task Center team."
  worker_target = {
    namespace_id = temporalcloud_namespace.tasks.id
    task_queue   = "task-center-nexus"
  }
  allowed_caller_namespaces = [temporalcloud_namespace.callers.id]
}
