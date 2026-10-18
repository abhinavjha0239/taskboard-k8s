# Taskboard on Kubernetes

A small to-do app (FastAPI + PostgreSQL, plain HTML page) taken from a bare
application to something that can be deployed, operated and explained on a
local Kubernetes cluster.

**Baseline** (first commit on `main`): the app only. It had a REST API, an HTML page,
SQLite or PostgreSQL via `DATABASE_URL`, and two unit tests. There was no container, no Kubernetes,
no CI, no health endpoints, no metrics/logs/traces and no secret handling.

**This PR adds:** a hardened container image, a Helm chart (web Deployment +
PostgreSQL StatefulSet), a resource-capped kind cluster, a CI/CD pipeline that
deploys every change to a throwaway cluster, release and rollback controls,
Prometheus metrics with SLO alerts, JSON logs, Jaeger traces, and security
checks across the pipeline and runtime. Evidence is in [EVIDENCE.md](EVIDENCE.md).

## Architecture

```
browser ─► 127.0.0.1:8080 ─► kind node :30080 (NodePort) ─► Service taskboard
                                                              │
                                    ┌─────────────────────────┴───────────┐
                                    ▼                                     ▼
                              web pod (:8000)                       web pod (:8000)
                                    │  SQL :5432                          │
                                    ▼                                     │
                     taskboard-postgres-0 (StatefulSet, 1Gi PVC) ◄────────┘

  Prometheus (observability ns) ── scrapes :9000/metrics on each web pod, evaluates alerts
  web pods ── OTLP/HTTP :4318 ─► Jaeger (observability ns)
```

Request path: `127.0.0.1:8080` is mapped by kind to NodePort 30080. kube-proxy forwards
it to the `taskboard` Service, which load-balances across **Ready** web pods only. A
pod reaches PostgreSQL by DNS name (`taskboard-postgres`, resolved by CoreDNS).

| Component | Kind | Why |
|---|---|---|
| web | Deployment, 2 replicas | Stateless, so any pod can serve. Two replicas keep serving during rollouts and pod failures. |
| postgres | StatefulSet, 1 replica + PVC | Stable name and its own volume. Data survives pod restarts and app rollbacks. |
| Prometheus, Jaeger | Deployments (`observability.yaml`) | Lightweight stand-ins for kube-prometheus-stack, which needs about 1.5 GB of RAM. |

### Failure boundaries

| Failure | What happens | How you see it |
|---|---|---|
| A web pod crashes or hangs | The other replica keeps serving. Liveness restarts the pod. | `up` drops, pod restarts |
| PostgreSQL down | Readiness fails, so pods leave the Service. Liveness ignores the DB, so pods do not restart in a loop. | `TaskboardDatabaseDown`, `/readyz` returns 503 |
| New image never becomes Ready | The rollout stalls while the old pods keep serving. Helm rolls back by itself after 3 min. | `helm history` shows the failed and rolled-back revisions |
| New release passes probes but returns errors | Users get 5xx responses. | `TaskboardHighErrorRate`, then `make rollback` |
| Prometheus or Jaeger down | The app is unaffected. Metrics are pulled and spans are exported asynchronously. | Gaps in metrics or traces |
| The node (the laptop) | Everything stops. Single-node local limitation. | — |

Linux and networking concepts used: non-root UIDs, read-only root filesystems, dropped capabilities and seccomp in every pod. cgroup limits per container, plus a cap on the whole node container. DNS service discovery. NodePort through kube-proxy. NetworkPolicies. Host ports bound to `127.0.0.1` only.

## Run it

Prerequisites: Docker (Desktop with ≥ 4 GB), [kind](https://kind.sigs.k8s.io) ≥ 0.33, kubectl, Helm 4, make, jq, openssl, python3.

```bash
make test       # optional: ruff, unit tests, helm lint (creates .venv)
make cluster    # kind cluster + Prometheus + Jaeger, ~2 min
make deploy     # build image for HEAD, load into kind, rolling deploy
make smoke      # user journey; fails if the running commit is not HEAD
make signals    # Prometheus scrapes both pods, alerts loaded, Jaeger has traces
make status     # helm history, pods with their version, /version
```

| What | Where |
|---|---|
| App | http://127.0.0.1:8080 (`/version`, `/healthz`, `/readyz`) |
| Prometheus (graphs, Alerts tab) | http://127.0.0.1:9090 |
| Jaeger traces | http://127.0.0.1:16686 |

Use `127.0.0.1` rather than `localhost`. kind publishes on IPv4 only, so if another program
listens on `[::1]:8080`, then `localhost` reaches that program instead.

**Laptop-friendly:** one node, capped with `docker update` at 2 CPUs and 3 GB. Every pod
has requests and limits. When you are done, run `make pause` to stop the node container
(state is kept), `make resume` to start it again, or `make down` to delete it.
`make help` lists all targets.

## CI/CD: from commit to running app

`.github/workflows/ci.yml` runs on every PR and every push to `main`:

1. **test**: `ruff` (lint and bandit security rules), format check, `pytest`, `helm lint`.
2. **security** (in parallel): gitleaks over the full git history, `pip-audit` on dependencies, trivy config scan of the Dockerfile, chart and manifests.
3. **deploy** (only if 1 and 2 pass): `make cluster`, `make build`, trivy image scan (fails on fixable HIGH/CRITICAL), `make deploy`, `make smoke`, `make drift`, `make signals`. These are the same commands used locally, so the pipeline and the laptop cannot drift apart.
4. **publish**: only an image that passed step 3 is pushed to `ghcr.io/<owner>/taskboard-k8s:<commit>`, using the built-in token. No stored credentials.

**Traceability.** The git commit SHA is the version everywhere:

- image tag `taskboard:<sha>` and OCI labels
- Helm revision description `deploy <sha>`
- pod label `app.kubernetes.io/version`
- `/version` endpoint, the `taskboard_build_info` metric, and the Prometheus `version` label

`make smoke` fails if `/version` does not return the expected commit.

**Where approval sits.** Merging a reviewed PR is the approval for `main`. Deploying to
the laptop cluster is a deliberate manual `make deploy`, because a hosted runner cannot
reach it. Every change is still deployed automatically to an ephemeral cluster in CI.

## Release control and recovery

- **Rolling update** with `maxSurge: 1, maxUnavailable: 0`, readiness gating, `minReadySeconds: 5` and a `preStop` sleep. Old pods serve until new ones are Ready, so there is no capacity dip.
- **Automatic rollback:** `helm upgrade --rollback-on-failure --wait --timeout 3m`. If the new pods never become Ready, Helm restores the previous revision.
- **Manual rollback** for a release that is healthy but wrong: `make rollback` (`helm rollback` and then the user journey). Helm keeps 10 revisions.
- **Drift:** `make drift` renders the chart from the repo at the deployed tag and runs a server-side `kubectl diff` against the live objects. A value changed by hand (`kubectl edit` or `kubectl scale`) shows up here. Helm 4 applies server-side, so without `--force-conflicts` it refuses to overwrite such a field. `make deploy` passes that flag so the repo always wins.
- **Data:** the PVC is untouched by app rollbacks. `make backup` writes a `pg_dump` file, which is git-ignored. The schema is create-if-missing only. Real schema changes would need to stay backward compatible so a rollback stays safe.

Why rolling and not canary or blue-green: this is one small app with one user. Canary
needs traffic splitting (an ingress controller or service mesh) and blue-green needs
double capacity, which a 3 GB laptop cluster cannot spare. Rolling updates with readiness
gating and automatic rollback cover the risk here. With real traffic I would add canary
analysis (for example Argo Rollouts gated on the error-rate SLO).

## Observability and reliability

**Healthy means:** both web pods Ready, at least 99% of `/api` requests non-5xx over 5 min,
p95 latency under 300 ms, `taskboard_db_up == 1`, and `make smoke` passing.

- **Metrics** (port 9000, never exposed by the Service):
  - `taskboard_http_requests_total{method,route,status}`
  - `taskboard_http_request_duration_seconds`, a histogram
  - `taskboard_db_up`
  - `taskboard_build_info{version,commit}`

  Routes are labelled by template (`/api/tasks/{task_id}`), so label cardinality stays bounded.
- **Logs:** one JSON object per request on stdout, with `trace_id`. For example: `make logs | jq 'select(.status >= 500)'`.
- **Traces:** OpenTelemetry spans for each HTTP request and SQL query, sent to Jaeger. A slow request can be followed to the exact query.
- **Probes:** `startupProbe` covers schema creation, `livenessProbe` checks the process only, and `readinessProbe` also checks the DB.

### Runbook

| Alert | First check | Action |
|---|---|---|
| `TaskboardDown` | `make status`, `kubectl -n taskboard describe pod` | Bad image or config: `make rollback`. Pending pods: check node resources. |
| `TaskboardHighErrorRate` | Did a release just happen? (`helm history`). `make logs \| jq 'select(.status>=500)'` | If it started with a release, `make rollback`. Otherwise follow a `trace_id` into Jaeger. |
| `TaskboardHighLatency` | Jaeger: slowest traces, HTTP span or SQL span? | DB slow: check postgres pod CPU and memory. App slow: check CPU throttling against the limits. |
| `TaskboardDatabaseDown` | `kubectl -n taskboard get pod taskboard-postgres-0`, then its logs | Restart the pod (data is on the PVC). Check the PVC and the secret. |

**Verify recovery:** the alert returns to *inactive* in Prometheus, `make smoke` passes,
and `make status` shows the expected version on all Ready pods. EVIDENCE.md walks through
a bad release, its detection and the rollback.

## Security

- **Secrets:** `make secret` generates the DB password inside the cluster (`openssl rand`). It reaches pods through `secretKeyRef`. It never appears in git, Helm values, the image or logs. CI uses only the short-lived `GITHUB_TOKEN`.
- **Runtime:**
  - Both namespaces enforce the `restricted` Pod Security Standard.
  - All containers run as non-root, with a read-only root filesystem, `drop: [ALL]` capabilities and the RuntimeDefault seccomp profile.
  - The app gets no service-account token.
  - Prometheus gets a Role that only lists pods in one namespace.
- **Network:**
  - NetworkPolicies: web accepts HTTP, and metrics only from `observability`. Web may only call PostgreSQL, DNS and Jaeger.
  - PostgreSQL accepts only web pods and has no egress.
  - Host ports bind to 127.0.0.1.
- **Pipeline:**
  - Scans: gitleaks, pip-audit, trivy (config and image), ruff `S` rules.
  - Actions are pinned to commit SHAs. Permissions are read-only by default, and only the deploy job may write packages.
- **Image:** multi-stage slim build, pip removed, UID 10001, build metadata in OCI labels.

## Decisions and what would change

| Choice | Why | Under different requirements |
|---|---|---|
| kind, 1 node, capped | Runs on a weak laptop. The same cluster is used in CI. | Managed cluster with several nodes, then topology spread and real PDB value |
| One `values.yaml` for local and CI | No environment copies to drift. Only the image tag changes. | Add `values-prod.yaml` (registry, replicas, storage class, ingress and TLS) |
| NodePort, no ingress controller | Single service. Saves memory. | Ingress or Gateway with TLS when there are hostnames and several services |
| 2 fixed replicas, no HPA | Load is tiny. metrics-server would cost RAM. | HPA on CPU or request rate |
| PostgreSQL in-cluster | Self-contained demo. | Managed DB with backups and point-in-time recovery |
| Plain Prometheus + Jaeger | Under 400 MB together. | kube-prometheus-stack, Alertmanager routing to chat or pager, Grafana |
| Manual local deploy | A hosted runner cannot reach a laptop. | GitOps (Argo CD) pulling from GHCR, with an environment approval |

## Known limitations

- Single node and a single PostgreSQL replica: no high availability for node or database failure.
- No automated backups. `make backup` is manual.
- Alerts appear only in the Prometheus UI. There is no Alertmanager to send notifications.
- Prometheus keeps 1 day of data and Jaeger keeps traces in memory. Both reset on restart.
- The GHCR package is private, so local deploys build the same Dockerfile instead of pulling.
- NetworkPolicy enforcement relies on kindnet, which supports it from kind v0.24.

## Local development without Kubernetes

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload    # SQLite, http://localhost:8000
```
