# ADR-0022 — The platform as a portfolio of data architectures, shown on getlagom.app

- **Status:** Accepted
- **Date:** 2026-10-28
- **Decided by:** the operator, in conversation on 2026-10-27 and 2026-10-28.

## Context and problem

The platform exists to prove that a solid data platform can run on minimal
infrastructure ([`CLAUDE.md`](../../CLAUDE.md) §1). After M2 it has a working
backbone (k3s, Argo CD, Sealed Secrets, CI gates, two environments) and one
pipeline: USGS earthquakes through dlt and dbt into Postgres. Nothing of it is
visible to anyone.

Several days went into infrastructure detail while no new data work was built.
Some of that order was right: GitOps, secrets, CI gates and the resource budget
are hard to fit after the fact. Some of it could have waited.

The operator wants the platform to show several data architectures side by
side — small, medium and, later, large-scale stacks — with their real numbers,
on the domain getlagom.app. The first goal is to show how much fits on a small
node, choosing stacks that are frugal with memory, which most of the market's
tools are not. Market-standard heavy stacks (Iceberg with Spark or Trino,
Airflow) come later.

## Decision

### Each architecture is a showcase on the shared backbone

A **showcase** is one data architecture end to end: ingestion, storage,
transformation, orchestration and its published results. Each has its own
namespace, its own Argo CD Application(s), its own line in the resource budget
and its own page on the site. Showcases share only the backbone. Removing one
breaks no other. They live in this repository: a separate repository is
justified only by a separate lifecycle, such as a stack that needs its own
cluster.

### The site is static, the computation is ephemeral

The site and its dashboards are static files on Cloudflare Pages: **no memory
on the node**, nothing to attack, and no database reachable from the internet.
Showcases compute as jobs, publish what they produced, and release their
memory. More showcases therefore cost scheduling, not resident memory, as long
as they do not run at the same time.

### The pieces

| Piece | Choice | Why |
|---|---|---|
| Orchestration | **Dagster**, in every showcase that needs a scheduler | orchestration and run history are needed even in the smallest showcase. It fits on the 8 GB node ([ADR-0020](0020-move-to-the-8-gb-node.md)), now obtained |
| Site | **Astro** on Cloudflare Pages, at getlagom.app | static, full design control. Design inspired by PostHog's, not a copy of it; copy states the problem, then the solution, without marketing |
| Dashboards | **Evidence**, its charts built on Apache ECharts | dashboards as code (SQL and Markdown, reviewed in pull requests), static output, no server. The site shows a gallery of cards; each opens one dashboard |
| Bridge from cluster to site | **Cloudflare R2** | Dagster exports each showcase's published tables as Parquet to R2, an outbound connection. CI builds Evidence from there, never reaching Postgres. Egress is free, which matters because visitors' browsers read Parquet directly. It speaks the S3 API, so the code is portable |

The site and the dashboards live under `products/`, the directory
[ADR-0006](0006-monorepo-layout.md) reserved for what a consumer sees.

### Order

1. **The 8 GB node and Dagster** (M3). The move to the new node is done by
   hand from the runbook, and **is the disaster-recovery drill**: built from
   Git on an empty machine, with its time measured.
2. **getlagom.app** (M4): the site, R2, Evidence, and the first showcase —
   **small data**, the existing USGS pipeline on Postgres.
3. **Medium data on a small node** (M5): DuckDB over Parquet (or Iceberg) on
   R2, with a dataset larger than the node's memory, and its benchmarks
   published.
4. **Streaming** (M6).
5. Heavier market stacks, later, each by its own trigger and ADR.

The public site needs **no login**: every showcase uses public data. Login
(Cloudflare Access) enters with the first content that must not be public.

## Alternatives considered

**Superset or Metabase for the dashboards.** The best-known BI servers.
Rejected for the public gallery: dashboards live in their metadata database,
not in Git, and a public dashboard queries the database live from the
internet. Both need 1 GB or more resident.

**Lightdash.** More active than Evidence (about 5,100 commits in the 90 days
before this ADR against about 108), with a semantic layer on dbt. Rejected for
now: viewing a dashboard without an account is in its source-available
directory, which needs a commercial agreement in production, and there is no
use case for self-service exploration yet.

**Streamlit.** An app framework, not a dashboard tool, and a resident server per
app. No use case today.

**ECharts or D3 used directly.** ECharts already comes through Evidence. Using
either directly for the gallery would rebuild what Evidence provides.

**AWS S3 instead of R2.** Same API. Rejected: egress is charged beyond 100 GB a
month, and the free offer ends; R2's egress is free and its free tier
permanent.

**Argo Workflows instead of Dagster.** About 100 MiB against Dagster's
measured ~550 MiB, and it fit the 4 GB node. Not needed once the 8 GB node
existed: Dagster gives assets, lineage and the dlt and dbt integrations.

## Consequences

**Positive.** The platform gets a public face and a purpose for each new
piece: a component enters because a showcase needs it. The node's memory
budget no longer grows with the number of showcases.

**Negative.**

- **Evidence's releases have paused.** Its npm package had no release between
  February and October 2026, although the repository is active. The exit is the
  Observable Framework, also static and Git-based: the dashboards' SQL and the
  Parquet stay, the chart layer is rewritten.
- **One vendor holds the public face.** DNS, Pages and R2 are all Cloudflare.
  A compromised account affects all three. Mitigation: a static site and the
  S3 API both move without rewriting.
- **Published data is public by design.** A showcase must never publish
  anything that is not already public. Private data needs login first.
- **Terraform is deferred again.** Its trigger was the disaster-recovery drill.
  The drill is the move to the new node, done by hand on purpose, to test the
  runbook as written. Terraform enters with the next node built or rebuilt.

## Risks, cost, and reversal

Cost: R2's free tier (10 GB, 1 million writes and 10 million reads a month) and
Cloudflare Pages' free plan. The node's cost is ADR-0020's.

Reversal: each showcase is removed by deleting its directory and Application;
the site is a separate build. Nothing in the backbone depends on the
portfolio.
