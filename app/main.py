from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select, update

from app import db
from app.config import settings
from app.db import engine, tasks

STATIC_DIR = Path(__file__).parent / "static"


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    done: bool | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db(settings.db_init_timeout_seconds)
    yield


app = FastAPI(title="Taskboard", version=settings.app_version, lifespan=lifespan)


def _row(r) -> dict:
    return {"id": r.id, "title": r.title, "done": r.done, "created_at": r.created_at}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz", include_in_schema=False)
def healthz():
    """Liveness: the process is up and serving. Deliberately ignores the database
    so a database outage makes pods unready instead of restarting them."""
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readyz():
    """Readiness: only receive traffic when the database is reachable."""
    try:
        db.ping()
    except Exception:
        return JSONResponse({"status": "unavailable", "database": "down"}, status_code=503)
    return {"status": "ready", "database": "up"}


@app.get("/version")
def version():
    return {"version": settings.app_version, "commit": settings.git_commit, "build_time": settings.build_time}


@app.get("/api/tasks")
def list_tasks():
    with engine.connect() as conn:
        rows = conn.execute(select(tasks).order_by(tasks.c.id)).all()
    return [_row(r) for r in rows]


@app.post("/api/tasks", status_code=201)
def create_task(body: TaskIn):
    with engine.begin() as conn:
        result = conn.execute(insert(tasks).values(title=body.title, done=False).returning(*tasks.c))
        return _row(result.one())


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, body: TaskPatch):
    values = body.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status_code=400, detail="nothing to update")
    with engine.begin() as conn:
        result = conn.execute(update(tasks).where(tasks.c.id == task_id).values(**values).returning(*tasks.c))
        row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    return _row(row)


@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    with engine.begin() as conn:
        result = conn.execute(delete(tasks).where(tasks.c.id == task_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="task not found")
