# ADR-0023 — The SME stack: DuckDB on DuckLake, Postgres as catalog, data on R2

- **Status:** Proposed — accepted or revised with the numbers of the spike in
  the roadmap (M3)
- **Date:** 2026-10-28
- **Decided by:** the operator, in conversation on 2026-10-28, pending the spike.
- **Would supersede, when accepted:** [ADR-0008](0008-postgres-for-all-layers.md)
  (every layer in Postgres) for the warehouse, and in
  [ADR-0022](0022-platform-as-a-portfolio-of-architectures.md) the tiers, R2's
  role, the publishing path and Terraform's timing.

## Context and problem

ADR-0022 made the platform a portfolio of showcases, in tiers (small, medium,
big data). The tiers mixed three different questions — where data rests, what
computes, who reads — and blurred the purpose.

The purpose, stated by the operator: **small and medium enterprises (SMEs) get
results fast on simple, solid infrastructure**, and most of what is sold as
big-data work does not need a big-data stack. The platform proves it with one
SME stack, and keeps a big-data stack only as a later comparison.

Postgres is the right engine for transactional work and serves many
concurrent readers well. It is a row store: analytical queries that scan and
aggregate large tables slow down as the data grows. DuckDB is a columnar,
vectorised engine that spills to disk instead of failing when memory runs
out. Both points are mainstream; the figures vendors publish for them are not
independent, so the spike measures them here.

## Decision

**Two tiers: SME and big data.**

### The SME stack

| Piece | Role |
|---|---|
| **DuckDB** | the engine: ingestion writes through it, dbt transforms with it (`dbt-duckdb`), dashboards query with it |
| **DuckLake** | the table format: Parquet files plus a catalog, with transactions, several concurrent writers, snapshots and schema evolution. 1.0 since April 2026 |
| **Postgres** | the **DuckLake catalog** — which files form which table, at which snapshot — and Dagster's metadata. Small, transactional and critical: what Postgres does best |
| **Cloudflare R2** | where the Parquet files rest. The node's local disk is DuckDB's spill and cache space |
| dlt, dbt, Dagster, Evidence | unchanged: dlt has a DuckLake destination, and its documentation names Postgres as the only production-grade catalog with full parallelism |

**Why R2 for the data files, not the local disk.** The data outlives the node.
Compute becomes stateless: the only state to protect is the catalog, a few
megabytes in Postgres. Backup reduces to the catalog
([ADR-0019](0019-postgres-backup-deferred.md)), and recovery to rebuilding the
node and restoring the catalog, with no re-load from the source. Capacity stops
being the node's disk, and staging can read prod's files with a read-only
token. The cost is network latency instead of NVMe, which DuckDB's range reads
and cache reduce, and which the spike measures.

**Dashboards are built in the cluster.** A Dagster step after each run builds
Evidence and publishes it to Cloudflare Pages, so the site follows the data,
not the code. CI is not involved, and no data leaves for the site except the
built pages.

### Big data

Apache Iceberg on object storage, a distributed engine (Spark or Trino) and
Airflow. **Later, by trigger**, as the comparison that shows where the SME stack
stops. Not planned in detail.

### Terraform with the move

The move to `lagom-shared-02` brings Terraform in, as the operator asked: it
must measure the recovery path that will be used. `lagom-shared-02` is
**imported**, not recreated, since 8 GB capacity was hard to obtain. Its own
ADR settles the state backend (HCP Terraform's free plan is the candidate).

## What the spike must show

On `lagom-shared-02`, with the USGS pipeline:

1. dlt loads into DuckLake (Postgres catalog, data on R2), and dbt-duckdb builds
   silver and gold with the same tests and reconciliations, passing.
2. **Evidence reads DuckLake.** No confirmed example of Evidence attaching a
   DuckLake catalog in Postgres was found. Fallback: a Dagster step exports
   gold to a DuckDB file that Evidence reads.
3. **Small files are handled.** Each 30-minute run writes small Parquet files;
   DuckLake's compaction runs as a scheduled job, and the R2 operation count
   stays within the free tier.
4. **Memory and time,** against the same pipeline on Postgres today: peak memory
   of each job, `dbt build` duration, query times on gold.

If any of these fails, this ADR is revised, not accepted.

## Consequences

**Positive.** One stack for the SME case, in which every piece does what it is
best at. Open files: any engine reads Parquet, so an SME that outgrows the
stack keeps its data. The node becomes disposable.

**Negative.**

- **DuckLake is young** — six months since 1.0 when this was written.
- **No server for interactive readers.** DuckDB serves one process; many
  concurrent readers mean the static dashboards, or a query service later.
- **`gold_reader` changes form.** Per-table grants exist in Postgres, not in
  DuckLake. Read-only access becomes a read-only R2 token plus a read-only role
  on the catalog.
- **One more dependency for the data itself:** R2, beyond Cloudflare's role for
  the site.

## Risks, cost, and reversal

Cost: R2's free tier, then US$0.015 per GB-month and per-operation charges
beyond the free counts; egress is free.

Reversal: the warehouse returns to Postgres (ADR-0008) — the dbt models are
re-targeted, and the Parquet files can be loaded back.

Sources checked on 2026-10-28:
[DuckLake catalog choice](https://ducklake.select/docs/stable/duckdb/usage/choosing_a_catalog_database),
[dlt DuckLake destination](https://dlthub.com/docs/dlt-ecosystem/destinations/ducklake),
[dbt on DuckLake](https://motherduck.com/docs/cookbook/dbt-local-ducklake.md),
[DuckDB vs Postgres (vendor article)](https://motherduck.com/learn/duckdb-vs-postgres-embedded-analytics/).
