.DEFAULT_GOAL := help
SHELL := /bin/bash

CLUSTER := taskboard
NS := taskboard
# Pin every command to the kind cluster so nothing lands on another context.
KUBECTL := kubectl --context kind-$(CLUSTER)
HELM := helm --kube-context kind-$(CLUSTER)
TAG ?= $(shell git rev-parse HEAD)
IMAGE := taskboard:$(TAG)
URL := http://127.0.0.1:8080
VENV ?= .venv

help: ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

$(VENV):
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r requirements-dev.txt

test: $(VENV) ## Lint, format check, unit tests, chart lint
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/python -m pytest -q
	helm lint chart --strict --set image.tag=lint

cluster: ## Create the kind cluster (1 node, capped at 2 CPU / 3 GB) with Prometheus and Jaeger
	kind get clusters | grep -qx $(CLUSTER) || kind create cluster --config kind.yaml --wait 2m
	docker update --cpus 2 --memory 3g --memory-swap 3g $(CLUSTER)-control-plane >/dev/null
	$(KUBECTL) create namespace $(NS) --dry-run=client -o yaml | $(KUBECTL) apply -f -
	$(KUBECTL) label namespace $(NS) --overwrite pod-security.kubernetes.io/enforce=restricted
	$(KUBECTL) apply -f observability.yaml
	$(KUBECTL) -n observability rollout status deploy/prometheus deploy/jaeger --timeout 3m

secret: ## Generate the database password inside the cluster (never on disk or in git)
	@$(KUBECTL) -n $(NS) get secret taskboard-db >/dev/null 2>&1 && echo "secret taskboard-db exists" || \
	  (openssl rand -hex 24 | tr -d '\n' | $(KUBECTL) -n $(NS) create secret generic taskboard-db --from-file=password=/dev/stdin)

build: ## Build the image for the current commit and load it into kind
	@test -z "$$(git status --porcelain --untracked-files=no)" || { echo "Uncommitted changes: commit first so the image matches a commit."; exit 1; }
	docker build -t $(IMAGE) --build-arg GIT_COMMIT=$(TAG) \
	  --build-arg APP_VERSION=$$(git describe --tags --always $(TAG)) --build-arg BUILD_TIME=$$(date -u +%FT%TZ) .
	kind load docker-image $(IMAGE) --name $(CLUSTER)

# --force-conflicts: the repo wins over fields changed by hand (see `make drift`).
deploy: build secret ## Rolling deploy of the current commit; Helm rolls back by itself if pods never get Ready
	$(HELM) upgrade --install taskboard chart -n $(NS) --set image.tag=$(TAG) $(ARGS) --force-conflicts \
	  --rollback-on-failure --wait --timeout 3m --history-max 10 --description "$(strip deploy $(TAG) $(ARGS))"
	$(HELM) history taskboard -n $(NS) --max 3

smoke: ## User journey against 127.0.0.1:8080, checking the running commit
	python3 scripts/smoke.py $(URL) $(TAG)

signals: ## Check Prometheus scrapes both pods, alert rules are loaded and Jaeger has traces
	@for i in $$(seq 30); do \
	  up=$$(curl -sG 127.0.0.1:9090/api/v1/query --data-urlencode 'query=sum(up{job="taskboard"})' | jq -r '.data.result[0].value[1] // 0'); \
	  [ "$$up" = 2 ] && break; sleep 3; done; echo "prometheus: $$up/2 web pods up"; [ "$$up" = 2 ]
	@sleep 16  # one rule evaluation, so alert states reflect the scrape above
	@curl -s 127.0.0.1:9090/api/v1/rules | jq -r '.data.groups[].rules[] | "alert \(.name): \(.state)"'
	@for i in $$(seq 20); do curl -s 127.0.0.1:16686/api/v3/services | jq -e '.services | index("taskboard")' >/dev/null && break; sleep 3; done; \
	  curl -s 127.0.0.1:16686/api/v3/services | jq -e '.services | index("taskboard")' >/dev/null && echo "jaeger: traces received from taskboard"

status: ## Release history, pods with their version, and what is answering
	$(HELM) history taskboard -n $(NS) --max 5
	$(KUBECTL) -n $(NS) get pods -o wide -L app.kubernetes.io/version
	@curl -s $(URL)/version; echo

rollback: ## Roll back to the previous Helm revision and re-run the user journey
	$(HELM) rollback taskboard -n $(NS) --wait --force-conflicts
	python3 scripts/smoke.py $(URL)

drift: ## Diff live objects against the chart in this repo (exit 1 = drift)
	@tag=$$($(HELM) get values taskboard -n $(NS) -o json | jq -r .image.tag); \
	helm template taskboard chart -n $(NS) --set image.tag=$$tag \
	  | $(KUBECTL) diff -n $(NS) --server-side --field-manager=drift-check --force-conflicts -f - \
	  && echo "no drift: live objects match the repo at $$tag"

logs: ## Follow JSON app logs
	$(KUBECTL) -n $(NS) logs -l app.kubernetes.io/component=web -f --max-log-requests 4

load: ## Generate traffic for metrics and traces (Ctrl-C to stop)
	while true; do curl -s -o /dev/null $(URL)/api/tasks; sleep 0.3; done

backup: ## pg_dump the database to ./backup-<time>.sql (git-ignored)
	$(KUBECTL) -n $(NS) exec taskboard-postgres-0 -- pg_dump -U taskboard taskboard > backup-$$(date +%Y%m%d-%H%M).sql

pause: ## Stop the cluster container to free CPU/RAM (state is kept)
	docker stop $(CLUSTER)-control-plane

resume: ## Start it again
	docker start $(CLUSTER)-control-plane

down: ## Delete the cluster
	kind delete cluster --name $(CLUSTER)

.PHONY: help test cluster secret build deploy smoke signals status rollback drift logs load backup pause resume down
