# Lagom Data Solutions

An open-source data platform that runs on minimal infrastructure, costs under
EUR 8 a month, and grows by composition.

Scarce RAM is expensive RAM, so cheap infrastructure is where small businesses
have to operate. Cheap should not mean fragile — it means designing against the
constraint instead of around it. This repository is the proof: a full platform
with ingestion, transformation, orchestration, GitOps delivery, reporting, and
data sharing, on a single 4 GB node.

> **Status:** M1 in progress — the node runs k3s, reachable over Tailscale; no
> workloads yet. See
> [`docs/roadmap.md`](docs/roadmap.md) for what exists and what is deliberately
> absent.

## How it works

```
External sources  ->  Ingestion        ->  Postgres
                      dlt / Redpanda       bronze / silver / gold, transformed by dbt
```

The proposed SME stack ([ADR-0023](docs/adr/0023-sme-stack-duckdb-on-ducklake.md)) keeps the data as Parquet
files on Cloudflare R2 in DuckLake, with Postgres as the catalog and DuckDB as
the engine. Until its spike passes, every layer lives in Postgres
([ADR-0008](docs/adr/0008-postgres-for-all-layers.md)).

Dagster orchestrates from outside the flow. Argo CD reconciles the cluster from
this repository. Readers see a static public site, getlagom.app, with no path to the cluster
([ADR-0022](docs/adr/0022-platform-as-a-portfolio-of-architectures.md)). Other access goes through one of three channels —
Tailscale for operators, Cloudflare Access for private content, signed URLs for
bulk data.

Full detail in [`docs/architecture.md`](docs/architecture.md).

## Stack

| Layer | Tool |
|---|---|
| Kubernetes | k3s on a Hetzner CAX11, Raspberry Pi as edge agent |
| GitOps | Argo CD |
| Batch ingestion | dlt |
| Event ingestion | Redpanda Connect |
| Storage | Postgres, every layer (lakehouse deferred with a trigger) |
| Transformation | dbt (`dbt-postgres`) |
| Orchestration | Dagster |
| Serving | Postgres |
| Reporting | Evidence (static pages; built by an ephemeral job, nothing resident) |

Every choice is recorded with its alternatives and trade-offs in
[`docs/adr/`](docs/adr/).

## Documentation

| Document | Read it when |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | always — operating rules for anyone working here |
| [`docs/architecture.md`](docs/architecture.md) | before touching a component; it holds the runbook |
| [`docs/roadmap.md`](docs/roadmap.md) | before adding a component |
| [`docs/adr/`](docs/adr/) | to understand why something is the way it is |
| [`docs/engineering-protocol.md`](docs/engineering-protocol.md) | before any task larger than a single file |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | before your first pull request |

Documentation is part of every change, not a follow-up — see
[`CLAUDE.md`](CLAUDE.md) §5.

## Getting started

The node is provisioned and bootstrapped by hand, step by step, from the
[runbook](docs/architecture.md#13-runbook) in `docs/architecture.md` — written
from commands that were actually executed. From Argo CD onwards, everything
reaches the cluster through a pull request.

## Layout

Divided by blast radius rather than by file type, so that adding a source or a
product is additive — see [ADR-0006](docs/adr/0006-monorepo-layout.md).

```
platform/            shared backbone — rarely changes, affects everything
  infra/             k8s manifests, Argo CD applications, Helm values  (M1)
  orchestration/     Dagster deployment and shared resources           (M3)
  warehouse/         the single dbt project                            (M2)
services/            workloads — change often, affect only themselves
  <service>/         ingestion + Dagster assets + tests, self-contained
products/            what a consumer sees
  <product>/         the getlagom.app site, Evidence dashboards
tools/               development and operational scripts
docs/                architecture, protocol, ADRs, runbook
.github/             CI: lint, types, tests, dbt parse, resource budget (M1); image builds, secret scan, promotion check (M2); manifest policy
.claude/             reviewer and implementer agents; denied git commands — CONTRIBUTING.md
```

**Directories are a convention, not scaffolding.** Each is created by the
milestone that fills it — the annotation above says which. Argo CD watches
`platform/infra/` only, so nothing outside that path can change the cluster.

## Tooling

`uv` for Python packaging, `ruff` for lint and formatting, `mypy` for types,
`sqlfluff` for SQL, `gitleaks` for secret scanning. Config files appear when the
code they check does.

## License

MIT — see [`LICENSE`](LICENSE).
