"""Runtime configuration, read once from environment variables.

Non-secret settings come from a ConfigMap; DB_PASSWORD comes from a Kubernetes
Secret. Build metadata (APP_VERSION, GIT_COMMIT, BUILD_TIME) is baked into the
image at build time so every running pod can report exactly what it is.
"""

import os
from dataclasses import dataclass
from urllib.parse import quote_plus


def _database_url() -> str:
    if url := os.getenv("DATABASE_URL"):
        return url
    if host := os.getenv("DB_HOST"):
        user = quote_plus(os.environ["DB_USER"])
        password = quote_plus(os.environ["DB_PASSWORD"])
        port = os.getenv("DB_PORT", "5432")
        name = os.getenv("DB_NAME", "taskboard")
        return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"
    return "sqlite:///./taskboard.db"


@dataclass(frozen=True)
class Settings:
    app_version: str = os.getenv("APP_VERSION", "dev")
    git_commit: str = os.getenv("GIT_COMMIT", "unknown")
    build_time: str = os.getenv("BUILD_TIME", "unknown")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    database_url: str = _database_url()
    db_init_timeout_seconds: float = float(os.getenv("DB_INIT_TIMEOUT_SECONDS", "60"))
    # Port for the Prometheus scrape endpoint; 0 disables it (used in tests).
    metrics_port: int = int(os.getenv("METRICS_PORT", "9000"))
    # Tracing is only enabled when an OTLP endpoint is configured.
    otel_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    otel_service_name: str = os.getenv("OTEL_SERVICE_NAME", "taskboard")


settings = Settings()
