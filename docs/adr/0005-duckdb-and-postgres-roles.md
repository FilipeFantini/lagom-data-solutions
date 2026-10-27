# ADR-0005 — DuckDB as compute engine, Postgres as operational spine

- **Status:** Accepted — partially superseded by [ADR-0008](0008-postgres-for-all-layers.md)
  (storage and compute layers deferred)
- **Date:** 2026-10-12

## Context and problem

The platform needs to process analytical workloads and to serve results to
dashboards, BI tools, and eventually an API. Running two databases invites the
reasonable objection that one should be enough.

The objection deserves a precise answer, because the first explanation of this
design was wrong: it presented DuckDB and Postgres as two databases competing
for the same role. They are not.

## Requirements and constraints

- Analytical processing of columnar data read from object storage.
- Concurrent access: ingestion writing, dbt writing, a dashboard reading.
- Low-latency reads for a dashboard polling every 10–30 seconds.
- Dagster needs a metastore that supports more than one user.
- Resident footprint must fit the budget in `architecture.md`.

## Alternatives considered

**DuckDB alone, exporting gold as static files.** Simpler, one fewer resident
process, and genuinely sufficient for a read-only dashboard. Rejected because
DuckDB is embedded and single-writer: with dbt writing, ingestion writing, and a
dashboard reading concurrently, it blocks. It also loses interactive filtering
and spatial queries, and Dagster would still need somewhere to keep state.

**Postgres alone, transforming in-database with `dbt-postgres`.** One tool
fewer, and attractive for that reason. Rejected because Postgres is
row-oriented and suffers on heavy aggregation, and because reading Parquet from
object storage is not its strength.

**A separate serving database per consumer.** Rejected as premature: no
consumer requires it yet.

## Decision

The two systems occupy different layers, and the layers are the point:

| Layer | Component | Replaceable by |
|---|---|---|
| Storage | open table format in object storage | nothing — it is the open format, it stays |
| Analytical compute | **DuckDB** | Trino, Spark, Snowflake |
| Transformation | dbt | — |
| Serving | **Postgres** | any application database |

**DuckDB is a processing engine**: ephemeral, started inside the job, reading the
table format directly from object storage, aggregating, writing back, exiting.

**Postgres is the operational spine**, with two roles independent of geographic
data: the **Dagster metastore** (run history and asset state, since the SQLite
default does not serve multiple users), and the **serving layer** for
dashboards, BI, and later an API.

Postgres holds only the small final result. Raw history stays in the table
format.

A third role considered and rejected: **Postgres as the table format catalog.**
With dlt writing to the filesystem and DuckDB reading by path, no catalog is
needed at this stage. Two roles are enough to justify Postgres; inventing a
third was overengineering.

PostGIS is a bonus when data is geographic and leaves the picture when it is
IoT. It is explicitly **not** part of the justification for Postgres, since the
platform must serve non-geographic domains equally well.

## Consequences

**Positive.** The layers are replaceable precisely because they are separate:
when volume outgrows DuckDB, the compute engine is swapped without touching
ingestion, storage, or consumers. Fusing everything into one database would bind
the platform to it. Each tool is also learned in the role the market actually
uses it in.

**Negative.** Two systems to operate instead of one, and a design that needs
this explanation to stop looking redundant — which is itself a cost. Postgres
carries 300 MB of resident RAM. Each Postgres connection costs 5–10 MB, so
external BI consumers will require PgBouncer.

## Risks, cost, and reversal

Low risk, and reversal is cheap in both directions: dropping Postgres means
exporting gold to static files and moving Dagster to SQLite (losing
multi-user support); dropping DuckDB means transforming with `dbt-postgres` at a
performance cost. Neither requires touching ingestion or storage, which is the
benefit the separation was chosen for.

## Notes after acceptance

- **2026-10-12 — storage and compute deferred.**
  [ADR-0008](0008-postgres-for-all-layers.md) keeps bronze, silver, and gold in
  Postgres until a measured trigger. The rejected alternative above, "Postgres
  alone", was rejected on heavy aggregation — a volume problem the platform
  does not have yet. The layer separation in this ADR remains the destination
  design; Postgres's two roles stand and gain a third until then.
