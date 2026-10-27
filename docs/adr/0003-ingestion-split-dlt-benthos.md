# ADR-0003 — Split ingestion: dlt for batch, Redpanda Connect for events

- **Status:** Accepted
- **Date:** 2026-10-12

## Context and problem

The platform's core premise is that it grows by composition: each new source is
another ingestion pipeline reusing the same backbone. Sources differ sharply in
nature, though. Some are batch APIs to be polled with incremental state; others
are continuous event streams.

The initial design used Redpanda Connect (formerly Benthos) for everything. With
a single full-refresh source that works. It stops working around the fifth
source.

## Requirements and constraints

- A new source should be configuration, not a new bespoke script.
- Zero resident RAM for batch ingestion — ephemeral compute is a core
  principle.
- Incremental extraction with durable state, so sources are not re-read whole.
- Schema changes at the source must not silently corrupt downstream data.
- Must support future IoT sources, which are event-based.

## Alternatives considered

**Redpanda Connect for everything.** Excellent at message pipelines, roughly
80 MB resident, declarative YAML, connectors for most transports including MQTT.
Weak at batch API extraction in five specific ways: pagination handling;
incremental cursor state across runs (achievable with `cache` resources, but
fragile); schema inference and evolution; normalization of nested JSON into
relational tables; and backfill of a historical window. Each of those becomes a
hand-built workaround, and half the configuration ends up being workaround.

**Airbyte.** Solves batch extraction properly, but needs Temporal, a worker, and
its own database. Excluded on resident RAM.

**Meltano with Singer taps.** Genuinely configuration-driven via `meltano.yml`,
with a large tap catalogue. Tap quality is uneven and the Python dependency
footprint is heavier. Kept as fallback.

**Hosted ELT (Fivetran and similar).** Excluded: paid SaaS, and already familiar
to the operator from daily work, so it closes none of the intended knowledge
gap.

**SQLMesh instead of dbt plus a separate orchestrator.** Would cover
transformation and scheduling in one lighter package. Rejected because dbt has
broader market relevance and learning dbt is an explicit goal.

## Decision

Two ingestion patterns, chosen by the nature of the source:

| Source nature | Tool |
|---|---|
| Batch API with incremental state | **dlt** as an ephemeral job/asset |
| Continuous events (MQTT, websocket, GTFS-RT) | **Redpanda Connect** -> NATS |

dlt is a library, not a server: `pip install`, run inside the job, exit. It
natively provides all five capabilities listed above. Its `rest_api` source
declares endpoints, paginator, auth, and incremental cursor as data, which keeps
"ingestion is configuration" true.

**NATS is deferred** with an explicit trigger — a second consumer of the same
stream, or a replay requirement. A source polled every 20 seconds can be written
straight to the destination by Redpanda Connect; introducing NATS earlier is a
deliberate learning exercise, labelled as such.

## Consequences

**Positive.** dlt removes code rather than adding a component: a net reduction in
complexity. It integrates natively with Dagster, so each pipeline becomes an
asset with lineage and no glue code. It generates a schema, giving dbt a typed
bronze layer instead of raw JSON, which removes casting scattered through
models. Symmetry improves: dlt is the EL to dbt's T, where before dbt had no
counterpart.

**Negative.** Two ingestion tools to learn and maintain instead of one. dlt
config is Python rather than YAML, which is a partial departure from
"configuration, not code" — it remains to be verified whether those blocks can
live in separate YAML and be loaded, which would close the gap.

## Risks, cost, and reversal

Low coupling: each pipeline is independent, so a source can be migrated between
tools without touching the others. If dlt proves wrong, Meltano is the fallback
and the storage layer below is unaffected.

Open item for M2: whether dlt source config can be externalized to YAML.
