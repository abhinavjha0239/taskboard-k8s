# Taskboard

A small to-do web app: a FastAPI backend with a plain HTML page. Tasks are stored with SQLAlchemy in SQLite by default, or PostgreSQL when `DATABASE_URL` is set.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload
```

Open http://localhost:8000.

To use PostgreSQL:

```bash
export DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/taskboard
```

## Test

```bash
.venv/bin/python -m pytest
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/tasks` | List tasks |
| POST | `/api/tasks` | Create a task `{"title": "..."}` |
| PATCH | `/api/tasks/{id}` | Update `title` and/or `done` |
| DELETE | `/api/tasks/{id}` | Delete a task |
