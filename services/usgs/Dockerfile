# Image for the USGS ingestion pipeline (ADR-0015). Build context: this
# directory. Two stages: the first resolves the locked dependencies into a
# virtual environment with uv; the second copies that environment and the
# source onto a clean base, so uv and everything else the build needed are not
# in the image that runs.

# The tag says which Python this is; the digest, the multi-arch index digest
# resolved on 2026-10-17 (it covers linux/arm64 and linux/amd64), is what is
# pulled. Moving to a newer base is a reviewed change to this line.
FROM python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS base

# The uv binary only. Same rule: exact version, pinned by digest.
FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv

FROM base AS build
COPY --from=uv /uv /usr/local/bin/uv
# UV_PYTHON_DOWNLOADS=never: use the base image's Python, never fetch another.
# UV_COMPILE_BYTECODE=1: compile .pyc now, because the root filesystem is
# read-only at run time and Python could not cache them then (startup of dlt
# is seconds slower without them).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /src
COPY pyproject.toml uv.lock ./
# --locked fails if uv.lock is out of date with pyproject.toml; --no-dev leaves
# out pytest, mypy, ruff, and the DuckDB test destination.
RUN uv sync --locked --no-dev

FROM base AS runtime
# A numeric UID so Kubernetes can verify runAsNonRoot. A passwd entry exists
# because some libraries look the user up by name.
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin lagom
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
# Source only: no tests, no fixtures, no lock file.
COPY ingestion/ ./ingestion/
# The paths dlt writes to are under /tmp, so the job can run with a read-only
# root filesystem and an emptyDir mounted at /tmp. HOME points there too, so
# nothing tries to create ~/.dlt.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    DLT_DATA_DIR=/tmp/dlt \
    RUNTIME__DLTHUB_TELEMETRY=false
LABEL org.opencontainers.image.source="https://github.com/FilipeFantini/lagom-data-solutions"
USER 10001:10001
# Arguments given to the container are appended: `--since ... --until ...`
# runs a backfill. The destination defaults to postgres; its credentials come
# from DESTINATION__POSTGRES__CREDENTIALS, set by the job, never baked in.
ENTRYPOINT ["python", "ingestion/pipeline.py"]
