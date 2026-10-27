# Image for the dbt project (ADR-0015). Build context: this directory. Same
# shape as services/usgs/Dockerfile: a build stage resolves the locked
# dependencies with uv, the runtime stage copies the environment and the
# project onto a clean base.

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
# read-only at run time and Python could not cache them then (dbt imports
# several hundred modules on every start).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /src
COPY pyproject.toml uv.lock ./
# --locked fails if uv.lock is out of date with pyproject.toml; --no-dev leaves
# out sqlfluff. One locked package, dbt-core-experimental-parser, ships as a
# source distribution whose build backend downloads the prebuilt wheel from
# github.com and checks its sha256; nothing is compiled, but this step needs
# network access to GitHub.
RUN uv sync --locked --no-dev

FROM base AS runtime
# A numeric UID so Kubernetes can verify runAsNonRoot. A passwd entry exists
# because some libraries look the user up by name.
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin lagom
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
# The project: dbt's `tests/` (reconciliation and generic tests) are part of
# `dbt build`, so unlike a service they ship. Not copied: README, .sqlfluff,
# pyproject.toml, uv.lock.
COPY dbt_project.yml profiles.yml ./
COPY macros/ ./macros/
COPY models/ ./models/
COPY tests/ ./tests/
# dbt's tracking is off, and HOME is under /tmp so nothing tries to create
# ~/.dbt on a read-only root filesystem. profiles.yml reads LAGOM_PG_* from the
# environment; the job supplies them and nothing is baked in.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    DO_NOT_TRACK=1
LABEL org.opencontainers.image.source="https://github.com/FilipeFantini/lagom-data-solutions"
USER 10001:10001
# dbt writes compiled SQL, the manifest, and logs; they go under /tmp so the
# job can run with a read-only root filesystem and an emptyDir at /tmp.
# Arguments given to the container are appended: `--select silver` narrows the
# build.
ENTRYPOINT ["dbt", "build", \
    "--project-dir", "/app", \
    "--profiles-dir", "/app", \
    "--target-path", "/tmp/dbt-target", \
    "--log-path", "/tmp/dbt-logs"]
