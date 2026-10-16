.DEFAULT_GOAL := help
SHELL := /bin/bash

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

cluster: ## Create the kind cluster (1 node, capped at 2 CPU / 3 GB)
	kind get clusters | grep -qx $(CLUSTER) || kind create cluster --config kind.yaml --wait 2m
	docker update --cpus 2 --memory 3g --memory-swap 3g $(CLUSTER)-control-plane >/dev/null
	$(KUBECTL) create namespace $(NS) --dry-run=client -o yaml | $(KUBECTL) apply -f -
	$(KUBECTL) label namespace $(NS) --overwrite pod-security.kubernetes.io/enforce=restricted

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

pause: ## Stop the cluster container to free CPU/RAM (state is kept)
	docker stop $(CLUSTER)-control-plane

resume: ## Start it again
	docker start $(CLUSTER)-control-plane

down: ## Delete the cluster
	kind delete cluster --name $(CLUSTER)

.PHONY: help test cluster secret build deploy pause resume down
