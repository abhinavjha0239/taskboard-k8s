import os

from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, create_engine, func

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./taskboard.db")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
metadata = MetaData()

tasks = Table(
    "tasks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", String(200), nullable=False),
    Column("done", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


def init_db() -> None:
    metadata.create_all(engine)
