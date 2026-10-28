# ADR-0008 — Postgres for every layer until the lakehouse has a measured trigger

- **Status:** Accepted — partially superseded by
  [ADR-0014](0014-develop-against-staging.md) (`dev` runs no local Postgres)
- **Date:** 2026-10-12
- **Partially supersedes:** [ADR-0005](0005-duckdb-and-postgres-roles.md)
  (storage and compute layers) and [ADR-0007](0007-three-environments.md)
  (the `dev` environment's DuckDB file and bucket prefix).
- **Defers:** [ADR-0004](0004-table-format.md) until the trigger below fires.

## Context and problem

The design put bronze and silver in an open table format on object storage,
transformed them with DuckDB, and served gold from Postgres
([ADR-0004](0004-table-format.md), [ADR-0005](0005-duckdb-and-postgres-roles.md)).
As a pattern it is coherent: a cheap store holds the full history, a fast
database serves the small result.

Choosing a storage provider exposed the question that had been skipped: **what
does the lake do now?** Nothing Postgres cannot. M2 has one source, USGS, with a
volume measured in megabytes. ADR-0005 rejected "Postgres alone with
`dbt-postgres`" because row-oriented storage suffers on heavy aggregation. That
is true at volume, and there is no volume. Principle 7 — defer with a trigger —
applies to the lake exactly as it applies to NATS. Kept without a trigger, the
lake would be stack added for its own sake.

The operator does want a lakehouse in this platform. That is the point of
waiting for a real reason: a migration driven by a measured limit teaches and
proves more than a lakehouse built for megabytes.

Two prices were checked while choosing a provider, and are recorded here for
when the trigger fires. Hetzner Object Storage bills a base fee for as long as
any bucket exists, even an empty one — EUR 6.49/month since April 2026 per
third-party trackers, EUR 4.99 on Hetzner's older press page — more than the
node itself. Cloudflare R2's free tier covers 10 GB-month, 1 million writes, and
10 million reads per month with free egress, but has no hard spending cap.

## Requirements and constraints

- Rebuild silver and gold after a bug fix without re-reading the source.
- Additive schema change in a source must not break ingestion
  ([`engineering-protocol.md`](../engineering-protocol.md) §16.3).
- Idempotent loads (§16.1).
- Fit the resident budget in [`architecture.md`](../architecture.md).
- Moving to a lakehouse later must not require rewriting ingestion or touching
  consumers.

## Alternatives considered

**Lakehouse on external object storage now (R2).** The previous plan. Rejected:
a vendor, a payment method, a credential per environment, uncapped operation
billing, and the table format test — all for megabytes, with no requirement
that needs them.

**Lakehouse on the node's own disk** — one local-path volume per namespace,
mirroring future buckets. Avoids the vendor, but keeps every other piece: the
table format, DuckDB, and the question of whether a table can be moved later
(Iceberg is understood to record absolute file paths in its metadata; unverified
here). Legitimate as a labelled learning exercise; the operator chose to wait
for a real reason instead.

**Postgres for every layer.** Chosen.

## Decision

**Bronze, silver, and gold are schemas in each environment's Postgres.** dlt
loads bronze; `dbt-postgres` builds silver and gold; consumers read gold.

- **Bronze is append-only and kept.** Replaying a transformation is re-running
  dbt, never re-reading the source.
- **Semi-structured payloads:** dlt normalizes nested JSON into typed child
  tables and adds columns when a source gains a field. Objects nested beyond
  `max_table_nesting` are stored as `JSONB` — parsed on write, queryable, and
  indexable. Large values are compressed out of line by Postgres (TOAST).
- **Binary data is not stored in Postgres.** A source that carries files is a
  trigger, below.
- **`dev` runs a local Postgres** on the operator's machine, same major version
  as the node. Developing against DuckDB while prod runs Postgres would test a
  different SQL dialect from the one deployed.
- **The Postgres backup still needs a destination off the node.** It is chosen
  when the backup is implemented (end of M2); R2's free tier is the candidate.
  That is a place for dump files, not a lakehouse.
- **Prefer portable SQL in dbt models** where Postgres-specific syntax buys
  nothing, because that is what the reversal below has to port.

### Trigger for the lakehouse

Object storage, an open table format, and DuckDB enter together when any of
these is **observed**, not anticipated:

1. A dbt model or query that Postgres handles badly within its memory budget —
   measured by run time, memory pressure, or an OOM kill.
2. Bronze history large enough to pressure the node's disk or make the backup
   slow — as a starting threshold, Postgres data above 10 GB of the 40 GB disk.
3. A source whose payload is files rather than records (images, documents).
4. A consumer that needs files rather than queries — the signed URL channel in
   [`architecture.md`](../architecture.md) §10.

When one fires, ADR-0004's test runs, the provider is chosen with the prices
above re-checked, and a new ADR records both.

## Consequences

**Positive.** M2 loses the table format test, DuckDB, object storage, and its
credentials. One SQL dialect across dev, staging, and prod. Concurrent writes
from ingestion and dbt with reads from a dashboard are handled by Postgres's
MVCC — the single-writer concern that ADR-0005 raised against DuckDB does not
arise. One backup captures every layer.

**Negative, stated plainly:**

- **Transformation runs inside a resident process**, not an ephemeral job. dbt
  itself still starts and exits, but its SQL executes in Postgres. This runs
  against principle 1 at volume; at megabytes it is irrelevant, and when it
  stops being irrelevant it is trigger 1.
- **Transformation and serving share one Postgres per environment.** A heavy
  model can slow dashboard reads. No quota separates them inside one pod.
- **Row storage is larger than columnar Parquet.** Irrelevant at megabytes;
  trigger 2 watches it.
- **The signed URL channel is unavailable** until object storage exists.
- **The 300 MB resident figure for Postgres** was set for serving, not for
  transformation. It is unverified under dbt load and is measured in M2.

## Risks, cost, and reversal

**Reversal is the lakehouse migration itself.** Gold stays in Postgres, so
consumers are untouched. dlt switches destination by configuration; bronze is
backfilled from the Postgres copy or from the source; dbt models are ported from
Postgres SQL to DuckDB SQL — close dialects, not identical. The cost grows with
the number of models, which is why portable SQL is preferred above.

The risk to watch is the trigger arriving unnoticed: a slow dbt run is easy to
tolerate one day at a time. The measures in trigger 1 and 2 belong in the M3
monitoring, not in someone's memory.

## Notes after acceptance

- **2026-10-12 — node price confirmed.** The node costs EUR 7.37/month
  ([ADR-0002](0002-single-node-k3s-hetzner.md)), so Hetzner Object Storage's
  base fee is comparable to the node, not larger than it as stated above. It
  would still nearly double the bill for megabytes of data; the decision is
  unchanged.
- **2026-10-28 — object storage and the lakehouse, after [ADR-0022](0022-platform-as-a-portfolio-of-architectures.md).**
  Object storage (R2) enters in M4, before any measured limit of Postgres, as
  the bridge that carries Parquet exports to the public site — not as a layer
  of the warehouse. The lakehouse (open table format, DuckDB) enters in M5 as a
  showcase of its own. The small-data showcase keeps every layer in Postgres,
  as decided above.
