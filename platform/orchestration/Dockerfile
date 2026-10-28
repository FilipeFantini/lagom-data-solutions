# The platform's Dagster code location (ADR-0026): Dagster, the services'
# assets and the dbt project, in one image. Built from the repository root,
# because it bundles directories from services/ and platform/:
#   docker build -f platform/orchestration/Dockerfile .
# The same image runs the code server (`dagster api grpc`, set by the Helm
# chart) and every run Pod the run launcher starts.

FROM python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS base

FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv

# uv exists only here: the runtime image gets the finished virtualenv.
FROM base AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /src
COPY platform/orchestration/pyproject.toml platform/orchestration/uv.lock ./
RUN uv sync --locked --no-dev

FROM base AS runtime
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin lagom
COPY --from=build /opt/venv /opt/venv
# The repository layout, kept under /app: definitions.py finds the dbt project
# and the services by their paths relative to it.
WORKDIR /app
COPY platform/orchestration/lagom_orchestration/ platform/orchestration/lagom_orchestration/
COPY services/usgs/ingestion/ services/usgs/ingestion/
COPY services/usgs/assets/ services/usgs/assets/
COPY platform/warehouse/dbt_project.yml platform/warehouse/profiles.yml platform/warehouse/
COPY platform/warehouse/macros/ platform/warehouse/macros/
COPY platform/warehouse/models/ platform/warehouse/models/
COPY platform/warehouse/tests/ platform/warehouse/tests/
# The root filesystem is read-only at run time; every writer goes to /tmp
# (an emptyDir): dlt's working files, dbt's logs and target, DuckDB's
# extensions (installed per run, under HOME).
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app:/app/platform/orchestration \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    DLT_DATA_DIR=/tmp/dlt \
    DBT_LOG_PATH=/tmp/dbt-logs \
    DO_NOT_TRACK=1 \
    RUNTIME__DLTHUB_TELEMETRY=false
# dagster-dbt reads the manifest when the code location loads, so it is built
# here. `dbt parse` reads the profile but opens no connection: the values below
# exist only for this step and are not in the image's environment.
RUN LAGOM_LAKE_CATALOG=ducklake:parse.ducklake LAGOM_LAKE_DATA_PATH=parse/ \
    LAGOM_LAKE_METADATA_SCHEMA=main LAGOM_R2_ACCESS_KEY_ID=parse \
    LAGOM_R2_SECRET_ACCESS_KEY=parse LAGOM_R2_ENDPOINT=https://parse.invalid \
    dbt parse --project-dir platform/warehouse --profiles-dir platform/warehouse \
      --target lake --log-path /tmp/dbt-logs --quiet \
    && rm -rf /tmp/dbt-logs
LABEL org.opencontainers.image.source="https://github.com/FilipeFantini/lagom-data-solutions"
USER 10001:10001
ENTRYPOINT ["dagster"]
