# Evidence

Everything below is real terminal output from commands run on 18 Oct 2026. Local times are
IST, CI times are UTC. Secret values are never printed.

| | |
|---|---|
| Tested commit | `390b92bef6353de3c63ae3e73412b977d341fefe`. This is the last change to code or configuration. The commit that adds this file changes nothing else, and CI deploys and verifies it again (see the PR). |
| Baseline | [`f801e96`](https://github.com/abhinavjha0239/taskboard-k8s/commit/f801e966857b4d8e46a73bf477af0c7a98a04e5d) on `main` |
| CI run | [Actions run 39142449083](https://github.com/abhinavjha0239/taskboard-k8s/actions/runs/39142449083): every job passed for `390b92b` |
| Published image | `ghcr.io/abhinavjha0239/taskboard-k8s:390b92bef6353de3c63ae3e73412b977d341fefe` (`sha256:06afb17f9e6f…b393b4`) |
| Local tools | macOS arm64, Docker Desktop, kind v0.33.0 (Kubernetes v1.37 node), Helm v4.1.4, kubectl v1.34.1 |

1. [Pipeline run for the commit](#1-pipeline-run-for-the-commit)
2. [Deploy: from commit to running pods](#2-deploy-from-commit-to-running-pods)
3. [User journey](#3-user-journey)
4. [Metrics, alerts, logs and traces](#4-metrics-alerts-logs-and-traces)
5. [Drift: detect and reconcile](#5-drift-detect-and-reconcile)
6. [Bad release: alert, rollback, recovery](#6-bad-release-alert-rollback-recovery)
7. [Broken release: automatic rollback](#7-broken-release-automatic-rollback)
8. [Database restart: readiness and persistence](#8-database-restart-readiness-and-persistence)
9. [Security controls at runtime](#9-security-controls-at-runtime)
10. [Resource caps](#10-resource-caps)
11. [What this evidence does not show](#11-what-this-evidence-does-not-show)

## 1. Pipeline run for the commit

| Job | Result | Duration |
|---|---|---|
| Lint, unit tests, chart lint | passed | 25 s |
| Secret, dependency and config scans | passed | 30 s |
| Build, scan, deploy to kind, verify | passed | 2 min 56 s |

Key lines from the job logs:

```
make test      All checks passed! | 8 files already formatted | 7 passed | 1 chart(s) linted, 0 chart(s) failed
gitleaks       no leaks found
pip-audit      No known vulnerabilities found
trivy config   Dockerfile 0 | chart/templates/postgres.yaml 0 | chart/templates/web.yaml 0 | observability.yaml 0 misconfigurations
trivy image    taskboard:390b92b… (debian 13.7): 0 HIGH/CRITICAL vulnerabilities
make deploy    STATUS: deployed  REVISION: 1
make smoke     PASS x5 (create, list, complete, delete, gone); /version commit = 390b92b…
make drift     no drift: live objects match the repo at 390b92b…
make signals   prometheus: 2/2 web pods up | 4 alerts inactive | jaeger: traces received from taskboard
GHCR push      390b92bef6353de3c63ae3e73412b977d341fefe: digest: sha256:06afb17f9e6f88b3b906c3444e4980a3426754e8f764b687966bcf88c3b393b4
```

## 2. Deploy: from commit to running pods

`make deploy` builds the image for HEAD, tags it with the commit, loads it into kind and
runs a Helm upgrade. The same SHA appears in the image tag, the Helm revision description,
the pod label `app.kubernetes.io/version` and `/version`.

```
$ git rev-parse HEAD
390b92bef6353de3c63ae3e73412b977d341fefe
$ make deploy
docker build -t taskboard:390b92bef6353de3c63ae3e73412b977d341fefe --build-arg GIT_COMMIT=390b92bef6353de3c63ae3e73412b977d341fefe \
	  --build-arg APP_VERSION=$(git describe --tags --always 390b92bef6353de3c63ae3e73412b977d341fefe) --build-arg BUILD_TIME=$(date -u +%FT%TZ) .
kind load docker-image taskboard:390b92bef6353de3c63ae3e73412b977d341fefe --name taskboard
Image: "taskboard:390b92bef6353de3c63ae3e73412b977d341fefe" with ID "sha256:b362495c9362d6c0d7396c8e8cb267733356ef2d03f19547e694697d86f9adaa" not yet present on node "taskboard-control-plane", loading...
secret/taskboard-db created
helm --kube-context kind-taskboard upgrade --install taskboard chart -n taskboard --set image.tag=390b92bef6353de3c63ae3e73412b977d341fefe  --force-conflicts \
	  --rollback-on-failure --wait --timeout 3m --history-max 10 --description "deploy 390b92bef6353de3c63ae3e73412b977d341fefe"
Release "taskboard" does not exist. Installing it now.
NAME: taskboard
LAST DEPLOYED: Sun Oct 18 21:23:17 2026
NAMESPACE: taskboard
STATUS: deployed
REVISION: 1
DESCRIPTION: deploy 390b92bef6353de3c63ae3e73412b977d341fefe
TEST SUITE: None
helm --kube-context kind-taskboard history taskboard -n taskboard --max 3
REVISION	UPDATED                 	STATUS  	CHART          	APP VERSION	DESCRIPTION
1       	Sun Oct 18 21:23:17 2026	deployed	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe
```

```
$ make status
helm --kube-context kind-taskboard history taskboard -n taskboard --max 5
REVISION	UPDATED                 	STATUS  	CHART          	APP VERSION	DESCRIPTION
1       	Sun Oct 18 21:23:17 2026	deployed	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe
kubectl --context kind-taskboard -n taskboard get pods -o wide -L app.kubernetes.io/version
NAME                         READY   STATUS    RESTARTS   AGE   IP            NODE                      NOMINATED NODE   READINESS GATES   VERSION
taskboard-6b4b4d4888-c2f5m   1/1     Running   0          20s   10.244.0.20   taskboard-control-plane   <none>           <none>            390b92bef6353de3c63ae3e73412b977d341fefe
taskboard-6b4b4d4888-ztwjx   1/1     Running   0          20s   10.244.0.21   taskboard-control-plane   <none>           <none>            390b92bef6353de3c63ae3e73412b977d341fefe
taskboard-postgres-0         1/1     Running   0          20s   10.244.0.23   taskboard-control-plane   <none>           <none>
{"version":"390b92b","commit":"390b92bef6353de3c63ae3e73412b977d341fefe","build_time":"2026-10-18T15:53:06Z"}
```

## 3. User journey

```
$ make smoke
python3 scripts/smoke.py http://127.0.0.1:8080 390b92bef6353de3c63ae3e73412b977d341fefe
version: {"version": "390b92b", "commit": "390b92bef6353de3c63ae3e73412b977d341fefe", "build_time": "2026-10-18T15:53:06Z"}
PASS: create task (HTTP 201)
PASS: task listed (HTTP 200)
PASS: complete task (HTTP 200)
PASS: delete task (HTTP 204)
PASS: task gone (HTTP 404)
```

## 4. Metrics, alerts, logs and traces

```
$ make signals
prometheus: 2/2 web pods up
alert TaskboardDown: inactive
alert TaskboardHighErrorRate: inactive
alert TaskboardHighLatency: inactive
alert TaskboardDatabaseDown: inactive
jaeger: traces received from taskboard
```

This follows one request from its JSON log line, by `trace_id`, to its trace in Jaeger.
The HTTP span took 12.1 ms. Inside it, opening a DB connection took 0.3 ms and the SQL
`INSERT` took 2.1 ms. Prometheus labels
traffic by route template and status, and `taskboard_build_info` ties each scraped pod to
a commit.

```
# One request followed from its log line to its trace
$ make logs | jq "select(.method==\"POST\")"   (one line)
{"ts": "2026-10-18T15:53:37.289+00:00", "level": "INFO", "logger": "taskboard", "msg": "request", "trace_id": "51661a2e3985938b28eeb9273c17d9ba", "span_id": "7809834141b13fda", "method": "POST", "path": "/api/tasks", "route": "/api/tasks", "status": 201, "duration_ms": 11.57}
$ curl 127.0.0.1:16686/api/v3/traces/51661a2e3985938b28eeb9273c17d9ba | jq '<span names and durations>'
connect  0.259 ms
INSERT taskboard  2.136 ms
POST /api/tasks http receive  0.079 ms
POST /api/tasks http send  0.013 ms
POST /api/tasks http send  0.017 ms
POST /api/tasks http send  0.004 ms
POST /api/tasks  12.07 ms

# Metrics: request rate by route/status and build info, straight from Prometheus
$ curl 127.0.0.1:9090/api/v1/query?query=sum by (route,status) (taskboard_http_requests_total)
/healthz 200 7
/readyz 200 12
/api/tasks/{task_id} 200 1
/api/tasks/{task_id} 404 1
/version 200 2
/api/tasks 201 1
/api/tasks 200 1
/api/tasks/{task_id} 204 1
$ curl 127.0.0.1:9090/api/v1/query?query=taskboard_build_info
taskboard-6b4b4d4888-ztwjx version=390b92bef6353de3c63ae3e73412b977d341fefe commit=390b92bef6353de3c63ae3e73412b977d341fefe value=1
taskboard-6b4b4d4888-c2f5m version=390b92bef6353de3c63ae3e73412b977d341fefe commit=390b92bef6353de3c63ae3e73412b977d341fefe value=1
```

## 5. Drift: detect and reconcile

A replica count changed by hand is reported as drift. `make deploy` puts the repo's value
back: Helm 4 server-side apply with `--force-conflicts`. Without that flag Helm refused
with `conflict with "kubectl" with subresource "scale": .spec.replicas`, which is why the
flag is in the Makefile.

```
$ make drift
no drift: live objects match the repo at 390b92bef6353de3c63ae3e73412b977d341fefe

# Someone scales by hand; drift check catches it
$ kubectl -n taskboard scale deploy/taskboard --replicas=3
deployment.apps/taskboard scaled
$ make drift
-  generation: 2
+  generation: 3
-  replicas: 3
+  replicas: 2
make: *** [drift] Error 1
$ make deploy   # reconcile from the repo
1       	Sun Oct 18 21:23:17 2026	superseded	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe
2       	Sun Oct 18 21:24:18 2026	deployed  	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe
$ make drift
no drift: live objects match the repo at 390b92bef6353de3c63ae3e73412b977d341fefe
```

## 6. Bad release: alert, rollback, recovery

- **Symptom:** after a release, half of the API calls return 500. All probes still pass, so Kubernetes and Helm both report the release as healthy.
- **Hypothesis:** the release introduced the problem. `helm history` shows a release made just before the errors started, with `--set app.chaosErrorRate=0.5` recorded in its description.
- **Evidence:**
  - `TaskboardHighErrorRate` goes from *pending* to *firing* after its `for: 2m`.
  - The JSON logs show `status: 500` entries with trace IDs.
  - `make smoke` fails.
- **Change:** `make rollback` returns to the previous Helm revision.
- **Verification:**
  - The user journey passes straight away.
  - With traffic still flowing, the 5-minute error ratio falls, and the alert returns to *inactive* once the bad minutes leave the window. (`n/a` means there were no 5xx samples in the window.)
  - `make status` shows the expected version on both pods.

```
## 1. Bad release: a config change that passes every probe but fails 50% of API calls
[21:24:48] $ make deploy ARGS="--set app.chaosErrorRate=0.5"
STATUS: deployed
REVISION: 3
REVISION	UPDATED                 	STATUS    	CHART          	APP VERSION	DESCRIPTION
1       	Sun Oct 18 21:23:17 2026	superseded	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe
2       	Sun Oct 18 21:24:18 2026	superseded	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe
3       	Sun Oct 18 21:24:59 2026	deployed  	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe --set app.chaosErrorRate=0.5
[21:25:17] $ make smoke
FAIL: create task (HTTP 500)
make: *** [smoke] Error 1

## 2. Detection: traffic running, watching the error-rate SLO alert
[21:25:17] 5xx ratio=n/a TaskboardHighErrorRate=inactive
[21:25:32] 5xx ratio=n/a TaskboardHighErrorRate=inactive
[21:25:47] 5xx ratio=0.5167 TaskboardHighErrorRate=pending
[21:26:02] 5xx ratio=0.5052 TaskboardHighErrorRate=pending
[21:26:17] 5xx ratio=0.4824 TaskboardHighErrorRate=pending
[21:26:32] 5xx ratio=0.4871 TaskboardHighErrorRate=pending
[21:26:47] 5xx ratio=0.4918 TaskboardHighErrorRate=pending
[21:27:02] 5xx ratio=0.4821 TaskboardHighErrorRate=pending
[21:27:17] 5xx ratio=0.4783 TaskboardHighErrorRate=pending
[21:27:32] 5xx ratio=0.4837 TaskboardHighErrorRate=pending
[21:27:47] 5xx ratio=0.4949 TaskboardHighErrorRate=firing
[21:27:47] $ make logs | jq 'select(.status>=500)'   (one line)
{"ts": "2026-10-18T15:57:46.131+00:00", "level": "ERROR", "logger": "taskboard", "msg": "request", "trace_id": "df986a2baba5c2d1e0f24ffed67149a2", "span_id": "9b03a7a087a0447b", "method": "GET", "path": "/api/tasks", "route": "/api/tasks", "status": 500, "dura
[21:27:48] $ helm history   (hypothesis: started with the last release)
REVISION	UPDATED                 	STATUS    	CHART          	APP VERSION	DESCRIPTION
1       	Sun Oct 18 21:23:17 2026	superseded	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe
2       	Sun Oct 18 21:24:18 2026	superseded	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe
3       	Sun Oct 18 21:24:59 2026	deployed  	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe --set app.chaosErrorRate=0.5

## 3. Change: roll back to the previous revision
[21:27:48] $ make rollback
Rollback was a success! Happy Helming!
version: {"version": "390b92b", "commit": "390b92bef6353de3c63ae3e73412b977d341fefe", "build_time": "2026-10-18T15:54:48Z"}
PASS: create task (HTTP 201)
PASS: task listed (HTTP 200)
PASS: complete task (HTTP 200)
PASS: delete task (HTTP 204)
PASS: task gone (HTTP 404)

## 4. Verify recovery: alert clears with traffic still running
[21:28:07] 5xx ratio=0.4903 TaskboardHighErrorRate=firing
[21:28:27] 5xx ratio=0.4550 TaskboardHighErrorRate=firing
[21:28:47] 5xx ratio=0.3941 TaskboardHighErrorRate=firing
[21:29:07] 5xx ratio=0.3592 TaskboardHighErrorRate=firing
[21:29:27] 5xx ratio=0.3289 TaskboardHighErrorRate=firing
[21:29:47] 5xx ratio=0.3068 TaskboardHighErrorRate=firing
[21:30:07] 5xx ratio=0.2864 TaskboardHighErrorRate=firing
[21:30:27] 5xx ratio=0.2614 TaskboardHighErrorRate=firing
[21:30:47] 5xx ratio=0.2270 TaskboardHighErrorRate=firing
[21:31:07] 5xx ratio=0.1959 TaskboardHighErrorRate=firing
[21:31:27] 5xx ratio=0.1622 TaskboardHighErrorRate=firing
[21:31:48] 5xx ratio=0.1332 TaskboardHighErrorRate=firing
[21:32:08] 5xx ratio=0.0990 TaskboardHighErrorRate=firing
[21:32:28] 5xx ratio=0.0578 TaskboardHighErrorRate=firing
[21:32:48] 5xx ratio=0.0156 TaskboardHighErrorRate=firing
[21:33:08] 5xx ratio=n/a TaskboardHighErrorRate=inactive
[21:33:08] $ make status
REVISION	UPDATED                 	STATUS    	CHART          	APP VERSION	DESCRIPTION
1       	Sun Oct 18 21:23:17 2026	superseded	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe
2       	Sun Oct 18 21:24:18 2026	superseded	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe
3       	Sun Oct 18 21:24:59 2026	superseded	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe --set app.chaosErrorRate=0.5
4       	Sun Oct 18 21:27:48 2026	deployed  	taskboard-0.1.0	0.1.0      	Rollback to 2
NAME                         READY   STATUS    RESTARTS   AGE     IP            NODE                      NOMINATED NODE   READINESS GATES   VERSION
taskboard-6b4b4d4888-2d895   1/1     Running   0          5m21s   10.244.0.30   taskboard-control-plane   <none>           <none>            390b92bef6353de3c63ae3e73412b977d341fefe
taskboard-6b4b4d4888-4j2zz   1/1     Running   0          5m11s   10.244.0.31   taskboard-control-plane   <none>           <none>            390b92bef6353de3c63ae3e73412b977d341fefe
taskboard-postgres-0         1/1     Running   0          8m32s   10.244.0.27   taskboard-control-plane   <none>           <none>
{"version":"390b92b","commit":"390b92bef6353de3c63ae3e73412b977d341fefe","build_time":"2026-10-18T15:54:48Z"}
```

## 7. Broken release: automatic rollback

Here the new pods can never become Ready (their image cannot be pulled). Because of
`maxUnavailable: 0`, the old pods keep serving the whole time. After the 3-minute timeout,
`--rollback-on-failure` restores the previous revision without anyone stepping in.

```
## Broken release: the new image cannot be pulled, so its pods never become Ready
[21:33:09] $ make deploy ARGS="--set image.repository=ghcr.io/abhinavjha0239/does-not-exist"

[21:33:49] While the rollout is stuck: old pods keep serving (maxUnavailable: 0)
$ kubectl -n taskboard get pods
NAME                         READY   STATUS             RESTARTS   AGE
taskboard-5d69cf9f54-4qcph   0/1     ImagePullBackOff   0          25s
taskboard-6b4b4d4888-2d895   1/1     Running            0          6m1s
taskboard-6b4b4d4888-4j2zz   1/1     Running            0          5m51s
taskboard-postgres-0         1/1     Running            0          9m12s
$ make smoke
version: {"version": "390b92b", "commit": "390b92bef6353de3c63ae3e73412b977d341fefe", "build_time": "2026-10-18T15:54:48Z"}
PASS: create task (HTTP 201)
PASS: task listed (HTTP 200)
PASS: complete task (HTTP 200)
PASS: delete task (HTTP 204)
PASS: task gone (HTTP 404)

[21:36:24] Helm gave up after the 3 min timeout and rolled back by itself:
	  --rollback-on-failure --wait --timeout 3m --history-max 10 --description "deploy 390b92bef6353de3c63ae3e73412b977d341fefe --set image.repository=ghcr.io/abhinavjha0239/does-not-exist"
Error: UPGRADE FAILED: release taskboard failed, and has been rolled back due to rollback-on-failure being set: resource Deployment/taskboard/taskboard not ready. status: InProgress, message: Updated: 1/2
make: *** [deploy] Error 1
exit=2
$ helm history taskboard
REVISION	UPDATED                 	STATUS    	CHART          	APP VERSION	DESCRIPTION
3       	Sun Oct 18 21:24:59 2026	superseded	taskboard-0.1.0	0.1.0      	deploy 390b92bef6353de3c63ae3e73412b977d341fefe --set app.chaosErrorRate=0.5
4       	Sun Oct 18 21:27:48 2026	superseded	taskboard-0.1.0	0.1.0      	Rollback to 2
5       	Sun Oct 18 21:33:23 2026	failed    	taskboard-0.1.0	0.1.0      	Upgrade "taskboard" failed: resource Deployment/taskboard/taskboard not ready. status: InProgress, message: Updated: ...
6       	Sun Oct 18 21:36:24 2026	deployed  	taskboard-0.1.0	0.1.0      	Rollback to 4
$ make smoke
version: {"version": "390b92b", "commit": "390b92bef6353de3c63ae3e73412b977d341fefe", "build_time": "2026-10-18T15:54:48Z"}
PASS: create task (HTTP 201)
PASS: task listed (HTTP 200)
PASS: complete task (HTTP 200)
PASS: delete task (HTTP 204)
PASS: task gone (HTTP 404)
```

## 8. Database restart: readiness and persistence

While PostgreSQL restarts, `/readyz` returns 503 and the pods leave the Service. They are
not restarted, because liveness ignores the DB. The task written before the restart is
still there afterwards, because it lives on the PVC.

```
# Data survives a database pod restart (PVC); web pods are not restarted
$ curl -X POST 127.0.0.1:8080/api/tasks -d {"title":"survive a restart"}
{"id":2,"title":"survive a restart","done":false,"created_at":"2026-10-18T15:54:36.686375+00:00"}
$ kubectl -n taskboard delete pod taskboard-postgres-0 --wait=false; sleep 2; curl 127.0.0.1:8080/readyz
pod "taskboard-postgres-0" deleted from taskboard namespace
{"status":"unavailable","database":"down"} HTTP 503
$ kubectl -n taskboard wait --for=condition=Ready pod/taskboard-postgres-0
pod/taskboard-postgres-0 condition met
$ curl 127.0.0.1:8080/readyz; curl 127.0.0.1:8080/api/tasks
{"status":"ready","database":"up"} HTTP 200
[{"id":2,"title":"survive a restart","done":false,"created_at":"2026-10-18T15:54:36.686375+00:00"}]
$ kubectl -n taskboard get pods
NAME                         READY   STATUS    RESTARTS   AGE
taskboard-6b4b4d4888-c2f5m   1/1     Running   0          91s
taskboard-6b4b4d4888-ztwjx   1/1     Running   0          91s
taskboard-postgres-0         1/1     Running   0          11s
```

## 9. Security controls at runtime

```
# Pod Security "restricted": a root pod is rejected in the taskboard namespace
$ kubectl -n taskboard run root-test --image=busybox --restart=Never -- id
Error from server (Forbidden): pods "root-test" is forbidden: violates PodSecurity "restricted:latest": allowPrivilegeEscalation != false (container "root-test" must set securityContext.allowPrivilegeEscalation=false), unrestricted capabilities (container "root-test" must set securityContext.capabilities.drop=["ALL"]), runAsNonRoot != true (pod or container "root-test" must set securityContext.runAsNonRoot=true), seccompProfile (pod or container "root-test" must set securityContext.seccompProfile.type to "RuntimeDefault" or "Localhost")

# NetworkPolicy: a pod outside the app cannot reach PostgreSQL
$ kubectl -n default run np-test --rm -i --restart=Never --image=busybox -- nc -zv -w 3 taskboard-postgres.taskboard 5432
nc: taskboard-postgres.taskboard (10.244.0.23:5432): Connection timed out

# NetworkPolicy: the metrics port is closed to everything except the observability namespace
$ kubectl -n default run np-test2 --rm -i --restart=Never --image=busybox -- wget -qO- -T 3 http://10.244.0.20:9000/metrics
wget: download timed out

# The app runs as non-root, with a read-only root filesystem and no service-account token
$ kubectl -n taskboard exec deploy/taskboard -- sh -c "id; touch /srv/x; ls /var/run/secrets"
uid=10001(app) gid=10001(app) groups=10001(app)
touch: cannot touch '/srv/x': Read-only file system
ls: cannot access '/var/run/secrets': No such file or directory
command terminated with exit code 2

# The DB password exists only as a Secret in the cluster (value not shown)
$ kubectl -n taskboard get secret taskboard-db
NAME           TYPE     DATA   AGE
taskboard-db   Opaque   1      79s
```

The CI checks for secrets, dependencies, configuration and the image are listed in section 1.

## 10. Resource caps

The whole cluster runs inside one container, capped at 2 CPUs and 3 GiB. Every pod has
requests and limits.

```
$ docker inspect taskboard-control-plane --format '{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}}'
NanoCpus=2000000000 (2 CPUs)  Memory=3221225472 (3 GiB)  MemorySwap=3221225472

$ docker stats --no-stream taskboard-control-plane
NAME                      CPU %     MEM USAGE / LIMIT
taskboard-control-plane   34.54%    1.86GiB / 3GiB

$ kubectl get pods -n taskboard,observability -o custom-columns=...resources
POD                          CPU_REQ   CPU_LIM   MEM_REQ   MEM_LIM
taskboard-6b4b4d4888-c2f5m   50m       500m      96Mi      192Mi
taskboard-6b4b4d4888-t98hv   50m       500m      96Mi      192Mi
taskboard-6b4b4d4888-ztwjx   50m       500m      96Mi      192Mi
taskboard-postgres-0         50m       500m      128Mi     256Mi
jaeger-6c6f685544-9vjwq       20m   300m   64Mi    256Mi
prometheus-7bc785c8df-6lqcz   50m   500m   128Mi   384Mi
```

## 11. What this evidence does not show

- **Node failure, and a PDB during a real drain.** The cluster has a single node.
- **Alert notifications.** There is no Alertmanager. Alert states were read from the Prometheus API (the Alerts page shows the same data).
- **The latency alert firing.** No load test was run. The rule is loaded and evaluated (section 4).
- **Restoring a `make backup` dump.** This was not drilled.
