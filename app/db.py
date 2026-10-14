import logging
import time

from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, create_engine, func, text

from app.config import settings

log = logging.getLogger(__name__)

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    # Fail fast when PostgreSQL is unreachable so readiness checks don't hang.
    connect_args={} if _is_sqlite else {"connect_timeout": 3},
)
metadata = MetaData()

tasks = Table(
    "tasks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", String(200), nullable=False),
    Column("done", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


def init_db(timeout_seconds: float) -> None:
    """Create the schema, retrying while the database is still starting."""
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    while True:
        attempt += 1
        try:
            metadata.create_all(engine)
            log.info("database schema ready", extra={"attempt": attempt})
            return
        except Exception as exc:
            if time.monotonic() >= deadline:
                log.error("database not reachable, giving up", extra={"attempt": attempt, "error": str(exc)})
                raise
            log.warning("database not ready, retrying", extra={"attempt": attempt, "error": str(exc)})
            time.sleep(min(2 * attempt, 5))


def ping() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
