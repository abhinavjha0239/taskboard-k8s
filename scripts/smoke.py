#!/usr/bin/env python3
"""End-to-end user journey against a running Taskboard.

    python3 scripts/smoke.py http://127.0.0.1:8080 [expected-commit]

Checks readiness, that /version reports the expected commit (so we know which
build answered), then creates, lists, completes and deletes a task. Exits
non-zero if any step fails. Standard library only, so it runs anywhere.
"""

import json
import sys
import time
import urllib.error
import urllib.request


def call(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    # Scheme is restricted to http(s) in main(), so file:// and friends can't be opened.
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        return err.code, None


def check(name: str, ok: bool, status: int) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}: {name} (HTTP {status})")
    return ok


def main() -> int:
    base = sys.argv[1].rstrip("/")
    if not base.startswith(("http://", "https://")):
        print(f"FAIL: base URL must be http(s), got {base!r}")
        return 2
    expected_commit = sys.argv[2] if len(sys.argv) > 2 else None

    for _ in range(30):
        try:
            if call(base, "GET", "/readyz")[0] == 200:
                break
        except OSError:
            pass
        time.sleep(2)
    else:
        print(f"FAIL: {base}/readyz never returned 200")
        return 1

    _, version = call(base, "GET", "/version")
    print(f"version: {json.dumps(version)}")
    if expected_commit and version["commit"] != expected_commit:
        print(f"FAIL: running commit {version['commit']} != expected {expected_commit}")
        return 1

    status, task = call(base, "POST", "/api/tasks", {"title": "smoke test"})
    if not check("create task", status == 201, status):
        return 1
    tid = task["id"]
    status, tasks = call(base, "GET", "/api/tasks")
    ok = check("task listed", status == 200 and any(t["id"] == tid for t in tasks), status)
    status, body = call(base, "PATCH", f"/api/tasks/{tid}", {"done": True})
    ok &= check("complete task", status == 200 and body["done"] is True, status)
    status, _ = call(base, "DELETE", f"/api/tasks/{tid}")
    ok &= check("delete task", status == 204, status)
    status, _ = call(base, "DELETE", f"/api/tasks/{tid}")
    ok &= check("task gone", status == 404, status)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
