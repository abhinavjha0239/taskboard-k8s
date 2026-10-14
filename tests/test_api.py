from fastapi.testclient import TestClient

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
