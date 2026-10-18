"""Logs, metrics and traces for the app.

- Logs: one JSON object per line on stdout, with trace_id when tracing is on,
  so `kubectl logs` output can be filtered with jq and joined to a trace.
- Metrics: Prometheus counters/histograms labelled by route template (not raw
  path) to keep label cardinality bounded. Served on a separate port (9000)
  that the Service never exposes; only Prometheus may reach it.
- Traces: OpenTelemetry spans for HTTP requests and SQL queries, exported over
  OTLP/HTTP when OTEL_EXPORTER_OTLP_ENDPOINT is set.
"""

import json
import logging
import sys
from datetime import UTC, datetime

from opentelemetry import trace
from prometheus_client import Counter, Gauge, Histogram, start_http_server

_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
    "color_message",  # uvicorn's ANSI-coloured duplicate of msg
}

HTTP_REQUESTS = Counter(
    "taskboard_http_requests_total",
    "HTTP requests handled, by method, route template and status code.",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "taskboard_http_request_duration_seconds",
    "HTTP request latency in seconds, by method and route template.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
DB_UP = Gauge("taskboard_db_up", "1 if the last readiness check reached the database, else 0.")
BUILD_INFO = Gauge("taskboard_build_info", "Build metadata of the running app.", ["version", "commit"])


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            entry["trace_id"] = format(ctx.trace_id, "032x")
            entry["span_id"] = format(ctx.span_id, "016x")
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Request logging is done by our middleware; uvicorn's access log would duplicate it.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True


def start_metrics_server(port: int, version: str, commit: str) -> None:
    BUILD_INFO.labels(version=version, commit=commit).set(1)
    if port:
        start_http_server(port)


def setup_tracing(app, engine, endpoint: str, service_name: str, version: str) -> None:
    if not endpoint:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name, "service.version": version}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")
    SQLAlchemyInstrumentor().instrument(engine=engine)
