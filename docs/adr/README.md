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
| [0001](0001-use-adrs.md) | Record architecture decisions in ADRs | Accepted; the Obsidian vault's role amended by 0034 |
| [0002](0002-single-node-k3s-hetzner.md) | Single-node k3s on a Hetzner CAX11 | Accepted, partially superseded by 0021 |
| [0003](0003-ingestion-split-dlt-benthos.md) | Split ingestion: dlt for batch, Redpanda Connect for events | Accepted |
| [0004](0004-table-format.md) | Open table format: Iceberg preferred, Delta as fallback | Proposed, deferred by 0008 |
| [0005](0005-duckdb-and-postgres-roles.md) | DuckDB as compute engine, Postgres as operational spine | Accepted, partially superseded by 0008 |
| [0006](0006-monorepo-layout.md) | Monorepo layout: platform, services, products | Accepted |
| [0007](0007-three-environments.md) | Three environments: dev local, staging and prod on one node | Accepted, partially superseded by 0008, 0014, 0015 and 0026 |
| [0008](0008-postgres-for-all-layers.md) | Postgres for every layer until the lakehouse has a measured trigger | Accepted, partially superseded by 0014 |
| [0009](0009-argocd-bootstrap-and-self-management.md) | Argo CD: pinned Helm chart, app of apps, self-managed | Accepted, decision 4 superseded by 0017 |
| [0010](0010-sealed-secrets.md) | Sealed Secrets for secrets in Git, key renewal off | Accepted |
| [0011](0011-memory-viability-on-4gb.md) | Memory viability on the 4 GB node, measured before M2 | Accepted, decision 3 superseded by 0016 |
| [0012](0012-cloudnative-pg.md) | CloudNativePG runs Postgres; backup mechanism chosen at its trigger | Accepted, partially superseded by 0019 |
| [0013](0013-agent-driven-development-guardrails.md) | Agent-driven development behind enforced guardrails | Accepted; rule 3 superseded and rule 2 amended by 0029 |
| [0014](0014-develop-against-staging.md) | Develop against staging, with no local services | Accepted |
| [0015](0015-images-on-ghcr.md) | Images built in CI, published privately to GHCR, promoted by digest | Accepted |
| [0016](0016-ci-ceiling-2-2-gb.md) | CI ceiling lowered to 2.2 GB from the measured overhead | Superseded by 0024 |
| [0017](0017-public-repository-from-a-snapshot.md) | Publish as a new public repository from a single-commit snapshot | Accepted |
| [0018](0018-pipeline-heartbeat.md) | Pipeline liveness by heartbeat to Healthchecks.io | Accepted |
| [0019](0019-postgres-backup-deferred.md) | Postgres backup deferred until the node holds state no source can rebuild | Accepted |
| [0020](0020-move-to-the-8-gb-node.md) | Move to the 8 GB node (CAX21) for M3, pending Hetzner capacity | Accepted |
| [0021](0021-k3s-packaged-components-under-git.md) | Traefik and servicelb disabled; local-path and metrics-server managed by Argo CD | Accepted |
| [0022](0022-platform-as-a-portfolio-of-architectures.md) | The platform as a portfolio of data architectures, shown on getlagom.app | Accepted, domain superseded by 0030 |
| [0023](0023-sme-stack-duckdb-on-ducklake.md) | The SME stack: DuckDB on DuckLake, Postgres as catalog, data on R2 | Proposed |
| [0024](0024-ci-ceiling-on-the-8-gb-node.md) | CI ceiling raised to 5.5 GB, measured on the 8 GB node | Accepted |
| [0025](0025-postgres-backup-barman-cloud-to-r2.md) | Postgres backup: the Barman Cloud plugin to Cloudflare R2, staging first | Accepted; retention checked 2026-11-05; RPO and prod retention superseded by 0027 |
| [0026](0026-dagster-one-instance-per-environment.md) | Dagster, one instance per environment, running USGS on DuckLake | Accepted, UI access superseded by 0028, then 0030 |
| [0027](0027-hourly-wal-archiving-and-14-day-prod-retention.md) | WAL archived hourly, prod backups kept 14 days | Accepted |
| [0028](0028-dagster-ui-over-the-tailnet.md) | Dagster's UI over the tailnet, by `tailscale serve` on the node | Superseded by 0030 |
| [0029](0029-agents-on-more-than-one-harness.md) | Agents on more than one harness: one rulebook, and who may merge | Accepted; Decision 3 amended and Tucano's rejection reversed by 0032 |
| [0030](0030-operator-uis-behind-cloudflare-access.md) | ofantini.com as the domain; operator UIs at ops.ofantini.com behind Cloudflare Access | Accepted |
| [0031](0031-repository-named-lagom.md) | The repository is named `lagom`; a rename to Robusta was tried and reverted | Accepted |
| [0032](0032-agents-in-credential-free-containers.md) | Agents run in containers that hold no credential, whatever runner starts them | Accepted |
| [0033](0033-dagster-alerts-through-healthchecks.md) | Dagster raises the alarm: a failure sensor and a heartbeat, both through Healthchecks.io | Proposed |
| [0034](0034-notion-as-the-one-documentation-space-outside-the-repo.md) | Notion is the one documentation space outside the repository | Proposed |
