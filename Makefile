SHELL := /bin/bash

.PHONY: setup up up-cloud down codegen smoke fee-change ci-approval example-notify example-input plan-endpoints

setup:       ## venv + Temporal CLI 1.9+
	scripts/setup.sh

up:          ## dev server, endpoints and every process; web UI on :8000
	scripts/up.sh

up-cloud:    ## same processes against Temporal Cloud (needs cloud.env, see config/cloud.env.example)
	scripts/up_cloud.sh

down:        ## stop the dev server
	scripts/down.sh

codegen:     ## OpenAPI -> Nexus contract -> Python, with nexgen (downloaded on first run)
	. scripts/env.sh && scripts/codegen.sh

smoke:       ## end-to-end checks against a running 'make up'
	. scripts/env.sh && $$PY scripts/smoke_test.py

fee-change:  ## billing team starts a fee change that needs approval
	. scripts/env.sh && $$PY -m teams.billing.start --change-id $${ID:-42}

ci-approval: ## a CI job asks a person to approve a release, over plain HTTP
	scripts/ci_approval.sh

example-notify: ## fire-and-forget a notification from plain Python
	. scripts/env.sh && $$PY -m examples.notify --reference example-$$RANDOM --wait

example-input:  ## ask a person for a decision from plain Python; answer it in the web UI
	. scripts/env.sh && $$PY -m examples.request_input --reference vendor-$$RANDOM

plan-endpoints: ## endpoint names, targets and allowlists for every environment and region
	. scripts/env.sh && $$PY scripts/plan_endpoints.py deploy/endpoints.yaml
