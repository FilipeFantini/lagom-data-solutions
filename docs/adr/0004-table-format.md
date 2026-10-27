# ADR-0004 — Open table format: Iceberg preferred, Delta as fallback

- **Status:** Proposed — deferred by [ADR-0008](0008-postgres-for-all-layers.md) until the lakehouse
  trigger fires; the test then runs as described below
- **Date:** 2026-10-12

## Context and problem

Bronze and silver layers live as files in object storage. Plain Parquet reads
and writes well but has no transactions, no updates, and no controlled schema
evolution. For a platform designed to take many sources over years — including
IoT — that hurts quickly: late-arriving data, record corrections, a sensor that
gains a field.

An open table format solves this. Which one is not obvious, because preference
and maturity point in different directions.

## Requirements and constraints

- ACID over files, schema evolution, and real `MERGE`.
- Open format, readable by any engine — no lock-in.
- Writable by dlt and readable by DuckDB, both in an ephemeral job.
- No catalog service to operate at this stage.
- Data volume is megabytes, so performance is not a differentiator.

## Alternatives considered

**Plain partitioned Parquet.** Sufficient for today's volume and the simplest
possible option. This nearly won the overengineering review. Rejected because
the capabilities above are needed by the fourth or fifth source, dlt provides a
table format almost for free, and the market expects familiarity with one.

**Apache Iceberg.** The operator's stated preference: broader adoption, more
engines, and the direction the industry is moving. DuckDB reads it well; write
support is more recent. dlt has a dedicated Iceberg destination, also newer than
its Delta path.

**Delta Lake.** The more mature write path today in both tools of this stack. In
dlt it uses the `deltalake` library with Parquet as the file format and is
documented in depth. Known limitations: no partition evolution; `merge`
restrictions with nested tables (`upsert` does not propagate element removal
inside JSON columns, `cdc` does); truncation retains old Parquet for time travel
until `vacuum` runs.

## Decision

**Iceberg is the preference. Delta is the fallback. The decision is settled by
testing both in M2**, writing the USGS bronze layer with each and reading it
back with DuckDB.

This ADR is `Proposed` until that test runs. The result will be recorded by
updating this ADR to `Accepted` with the measured outcome, naming the format
chosen and why.

**Rule for this phase either way:** no catalog, no optimization, no snapshot
maintenance. Write and read by path only. Standing up Nessie or Polaris here
would be pure excess.

## Consequences

**Positive.** Either choice is an open format, so the storage layer stays
engine-independent: the compute engine can be swapped later without touching
ingestion or consumers. Schema evolution and `MERGE` become available before
they are urgently needed.

**Negative.** One more concept between the file and the query, with its own
failure modes. If Delta wins, it is a conscious trade of market preference for a
more reliable write path — the same category of open format, not a concession.

## Risks, cost, and reversal

Reversal is real but not free: switching format means rewriting bronze and
silver from source. Mitigated by the fact that bronze is reproducible from the
sources — USGS exposes a 30-day window, so an early switch costs a re-run rather
than data loss.

The chief risk is discovering write immaturity only after building on it, which
is exactly why the test is scheduled before the format is cemented.

## Notes after proposal

- **2026-10-12 — deferred.** [ADR-0008](0008-postgres-for-all-layers.md) keeps
  every layer in Postgres until a measured trigger. "M2" above now reads "when
  the lakehouse trigger fires".
- **2026-10-12 — one more test criterion.** A table must survive being moved to
  another storage location, since the lake may start on one and move to
  another. Iceberg is understood to record absolute file paths in its metadata,
  which would make a move a metadata rewrite rather than a copy; Delta's log is
  understood to use relative paths. Both are unverified and belong in the test.
