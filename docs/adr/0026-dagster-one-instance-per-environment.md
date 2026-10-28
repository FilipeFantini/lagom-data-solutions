# ADR-0026 — Dagster, one instance per environment, running USGS on DuckLake

- **Status:** Accepted
- **Date:** 2026-10-28
- **Decided by:** the operator, on 2026-10-28, choosing one instance per
  environment over a single instance for both.
- **Supersedes:** in [ADR-0007](0007-three-environments.md), "staging runs no
  Dagster". The reason given there was memory on the 4 GB node, and it no
  longer holds ([ADR-0024](0024-ci-ceiling-on-the-8-gb-node.md)).

## Context and problem

M3 brings Dagster: assets, lineage, retries and run history for every
showcase ([ADR-0022](0022-platform-as-a-portfolio-of-architectures.md)). The
USGS pipeline runs today as two CronJobs, dlt and then dbt, into Postgres. The
next step is the SME stack ([ADR-0023](0023-sme-stack-duckdb-on-ducklake.md),
proposed): dlt into DuckLake, data on R2, catalog in Postgres, dbt-duckdb on
top. A local run on 2026-10-28 showed that the pieces work together: dbt
`PASS=33`, with DuckDB pinned to 1.5.x because 2.0 breaks dlt 1.31.

Postgres is backed up since 2026-10-28
([ADR-0025](0025-postgres-backup-barman-cloud-to-r2.md)), so Dagster's run
history can live there.

## Alternatives considered

**One Dagster for both environments.** One UI, about 550 MiB less. Rejected.
Each run is a Pod in its environment's namespace, and that Pod writes events
straight to Dagster's metadata database. Staging's runs would have to reach
it, so either:

- the metadata goes in prod's Postgres, and prod's NetworkPolicy, which denies
  staging, has to open; or
- the metadata goes in a third Postgres, which a staging run could still use
  to write into prod's history.

Both break the isolation that makes staging real ([ADR-0007](0007-three-environments.md)).

**Dagster in prod only**, as ADR-0007 said. Rejected: Dagster upgrades and
asset changes would reach prod untested.

## Decision

- **One Dagster per environment**, in the environment's namespace. Each is the
  `dagster/dagster` chart (1.13.27): webserver, daemon, one code location,
  runs launched as Kubernetes Jobs in the same namespace. Two runs of the
  pipeline never overlap: the run queue limits them by tag, as the CronJob's
  `concurrencyPolicy: Forbid` does. Its metadata is a
  database `dagster` in that environment's Postgres, owned by a role
  `dagster` whose password is generated and sealed by the operator. The
  database is backed up with the rest of the Cluster.
- **One code location for the platform**, image `lagom-orchestration`, built
  from `platform/orchestration/`. It holds Dagster's definitions, each
  service's assets (`services/<service>/assets/`, [ADR-0006](0006-monorepo-layout.md))
  and the dbt project (`platform/warehouse/`), whose models become assets
  through `dagster-dbt`. Its digest is promoted staging, then prod, like
  every image ([ADR-0015](0015-images-on-ghcr.md)).
- **USGS on DuckLake is its first content:**
  - dlt loads into DuckLake, with the catalog in the environment's Postgres
    and the data in its R2 bucket (`lagom-<env>-lake`);
  - dbt-duckdb builds silver and gold with the same tests;
  - a schedule runs it every 30 minutes;
  - compaction is a scheduled job of its own.

  The CronJobs on Postgres keep running until this path has run a week in
  prod and ADR-0023 is accepted or revised with its numbers.
- **The UI is reached by `kubectl port-forward`** over the tailnet, as
  Postgres is. Dagster's open-source UI has no login, so the kubeconfig is
  the access control. No ingress.
- **Heartbeat:** while the CronJobs run, they keep pinging Healthchecks.io
  ([ADR-0018](0018-pipeline-heartbeat.md)), and Dagster's runs are watched in
  its UI. Before the CronJobs are removed, Dagster takes over the alarm. That
  means native failure alerting (a roadmap item) or a ping after each
  successful run.

## Consequences

**Positive.** Staging stays isolated and exercises everything prod will run.
The run history is backed up. Every later showcase is one more set of assets
in the same code location, or a second code location.

**Negative.**

- **About 550 MiB of resident requests per environment**, from ADR-0011's
  spike: webserver ~130, daemon ~200, code server ~215 MiB. Runs are
  ephemeral Pods of ~250–300 MiB. Staging's ResourceQuota and LimitRange are
  raised to fit, and the figures are corrected by measurement.
- **Two new sealed secrets per environment:** the `dagster` role's password
  and the R2 token for the lake bucket.
- **Two pipelines write the same data** for a while: the CronJobs into
  Postgres and Dagster into DuckLake. They do not share tables.
- **The image build needs a repository-root context,** since the code
  location bundles services and the dbt project. `images.yml` gains a
  Dockerfile path per image, which is a CI change.

## Risks, cost, and reversal

Cost: R2's free tier.

The main risk is DuckLake on R2 through dlt and dbt-duckdb inside a Pod, which
the local run did not cover: the catalog in Postgres and the files on R2 were
not tested there. The first staging runs are the test. If they fail, ADR-0023
is revised, and Dagster can orchestrate the Postgres pipeline instead.

Reversal: delete the two Applications. Each database `dagster` stays, holding
the history.
