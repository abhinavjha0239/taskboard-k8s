# syntax=docker/dockerfile:1

# ---- build stage: install dependencies into a virtualenv ----
FROM python:3.13-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY requirements.txt .
# pip is only needed to build: drop it so its vendored libraries (often flagged
# by scanners) and the ability to install packages don't ship in the image.
RUN /opt/venv/bin/pip install -r requirements.txt && /opt/venv/bin/pip uninstall -y pip

# ---- runtime stage: only the venv and the app, running as a non-root user ----
FROM python:3.13-slim AS runtime

ARG APP_VERSION=dev
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown

LABEL org.opencontainers.image.title="taskboard" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_TIME}"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION} \
    GIT_COMMIT=${GIT_COMMIT} \
    BUILD_TIME=${BUILD_TIME}

RUN python -m pip uninstall -y pip \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app

WORKDIR /srv
COPY --from=build /opt/venv /opt/venv
COPY app ./app

USER 10001:10001
EXPOSE 8000 9000

# Single worker per container: scale by adding pods, which keeps Prometheus
# metrics per-process and lets Kubernetes do the load balancing.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--timeout-graceful-shutdown", "20"]
