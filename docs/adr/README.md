# Architecture Decision Records

Each ADR records one decision with lasting consequence: context, alternatives,
decision, consequences, and how to reverse it.

**Rules**

- A decision is reversed by a **new ADR that supersedes the old one**. The
  superseded ADR stays in place, marked `Superseded by ADR-NNNN`. History is
  never edited to look consistent.
- Numbering is sequential and never reused.
- Status is one of: `Proposed`, `Accepted`, `Superseded`, `Rejected`.
- Write an ADR when the decision shapes the system — not for routine choices.
  Re-introducing a practice excluded in
  [`../engineering-protocol.md`](../engineering-protocol.md) §17 requires one.

**Template:** copy [`0001-use-adrs.md`](0001-use-adrs.md) and keep its headings.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-use-adrs.md) | Record architecture decisions in ADRs | Accepted |
| [0002](0002-single-node-k3s-hetzner.md) | Single-node k3s on a Hetzner CAX11 | Accepted |
| [0003](0003-ingestion-split-dlt-benthos.md) | Split ingestion: dlt for batch, Redpanda Connect for events | Accepted |
| [0004](0004-table-format.md) | Open table format: Iceberg preferred, Delta as fallback | Proposed, deferred by 0008 |
| [0005](0005-duckdb-and-postgres-roles.md) | DuckDB as compute engine, Postgres as operational spine | Accepted, partially superseded by 0008 |
| [0006](0006-monorepo-layout.md) | Monorepo layout: platform, services, products | Accepted |
| [0007](0007-three-environments.md) | Three environments: dev local, staging and prod on one node | Accepted, partially superseded by 0008, 0014 and 0015 |
| [0008](0008-postgres-for-all-layers.md) | Postgres for every layer until the lakehouse has a measured trigger | Accepted, partially superseded by 0014 |
| [0009](0009-argocd-bootstrap-and-self-management.md) | Argo CD: pinned Helm chart, app of apps, self-managed | Accepted, decision 4 superseded by 0017 |
| [0010](0010-sealed-secrets.md) | Sealed Secrets for secrets in Git, key renewal off | Accepted |
| [0011](0011-memory-viability-on-4gb.md) | Memory viability on the 4 GB node, measured before M2 | Accepted, decision 3 superseded by 0016 |
| [0012](0012-cloudnative-pg.md) | CloudNativePG runs Postgres; backup mechanism chosen at its trigger | Accepted |
| [0013](0013-agent-driven-development-guardrails.md) | Agent-driven development behind enforced guardrails | Accepted |
| [0014](0014-develop-against-staging.md) | Develop against staging, with no local services | Accepted |
| [0015](0015-images-on-ghcr.md) | Images built in CI, published privately to GHCR, promoted by digest | Accepted |
| [0016](0016-ci-ceiling-2-2-gb.md) | CI ceiling lowered to 2.2 GB from the measured overhead | Accepted |
| [0017](0017-public-repository-from-a-snapshot.md) | Publish as a new public repository from a single-commit snapshot | Accepted |
| [0018](0018-pipeline-heartbeat.md) | Pipeline liveness by heartbeat to Healthchecks.io | Accepted |
