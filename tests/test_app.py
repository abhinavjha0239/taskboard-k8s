from fastapi.testclient import TestClient

from app import db
from app.main import app


def test_task_lifecycle():
    with TestClient(app) as client:
        created = client.post("/api/tasks", json={"title": "write tests"})
        assert created.status_code == 201
        task = created.json()
        assert task["title"] == "write tests"
        assert task["done"] is False

        listed = client.get("/api/tasks").json()
        assert any(t["id"] == task["id"] for t in listed)

        patched = client.patch(f"/api/tasks/{task['id']}", json={"done": True})
        assert patched.status_code == 200
        assert patched.json()["done"] is True

        assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
        assert client.delete(f"/api/tasks/{task['id']}").status_code == 404


def test_validation():
    with TestClient(app) as client:
        assert client.post("/api/tasks", json={"title": ""}).status_code == 422
        assert client.patch("/api/tasks/1", json={}).status_code == 400


def test_liveness_ignores_database_but_readiness_does_not(monkeypatch):
    def broken():
        raise RuntimeError("db down")

    with TestClient(app) as client:
        assert client.get("/readyz").json() == {"status": "ready", "database": "up"}
        monkeypatch.setattr(db, "ping", broken)
        assert client.get("/healthz").status_code == 200
        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert ready.json()["database"] == "down"


def test_version_reports_build_metadata():
    with TestClient(app) as client:
        body = client.get("/version").json()
    assert body["version"] == "test"
    assert body["commit"] == "0" * 40
