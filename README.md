# Lagom Data Solutions

An open project that combines open-source stacks to deliver data solutions on
minimal infrastructure.

**The problem.** Most organisations do not have big data. Their data fits on
one machine, often in its memory. Yet the default answer is a stack sized for
volumes they will never reach: distributed engines, warehouses billed per
query, and many resident services to operate. The cost and the
operational weight come from the tools, not from the data.

**What this project does.** It puts together open-source tools that each do
one job with little resident memory: ingestion, transformation,
orchestration, GitOps delivery and publishing. The platform runs on a single
small node and grows by composition: a new source is one more pipeline on the
same backbone. Each architecture is measured (rows, run time, memory) and
will be shown with those numbers on getlagom.app (M4), so the claim "you do
not need a big-data stack" can be checked, not just believed. A big-data stack enters later, as the comparison
that shows where the small one stops
([ADR-0023](docs/adr/0023-sme-stack-duckdb-on-ducklake.md), proposed).

Two rules hold throughout. **Cheap must not mean fragile:** the resource
budget is a constraint designed against, with tests, data reconciliation,
GitOps and a rehearsed disaster recovery. **The operator must understand the
system:** every choice is recorded with its alternatives and trade-offs.

> **The name.** *Lagom* is a Swedish word for "not too little, not too much —
> just enough". It is the design rule here: as much infrastructure as the data
> needs, and no more.

> **Status:** M3 in progress. One pipeline (USGS earthquakes: dlt, then dbt)
> runs every 30 minutes in staging and prod on a single 8 GB node; the
> platform was rebuilt on it in 20 minutes once the server existed, as a
> disaster-recovery drill: everything from Git, the sealing key from its
> backup, and the last 30 days of data re-loaded from the source. Next: Dagster and the SME-stack spike. See
> [`docs/roadmap.md`](docs/roadmap.md) for what exists and what is
> deliberately absent.

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
| Kubernetes | k3s on one ARM node (Hetzner CAX21, 8 GB); a Raspberry Pi as edge agent (M6) |
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
