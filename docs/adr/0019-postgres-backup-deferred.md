# ADR-0019 — Postgres backup deferred until the node holds state no source can rebuild

- **Status:** Accepted
- **Date:** 2026-10-27
- **Supersedes:** the timing of the backup, "end of M2", in the roadmap and in
  [ADR-0012](0012-cloudnative-pg.md) ("Backup: deferred, no placeholder"). The
  choice of mechanism in ADR-0012 stands.

## Context and problem

The roadmap pulled the Postgres backup forward from M7 to the end of M2, on
the grounds that infrastructure is reproducible from Git and Postgres state is
not. M2 is otherwise done: the pipeline runs in staging and prod, with tests,
grants and a heartbeat ([ADR-0018](0018-pipeline-heartbeat.md)).

On 2026-10-27 the operator decided backup is not a priority now: nothing
critical runs on the platform. The question this ADR answers is when it
becomes one, stated as a trigger that can be checked rather than a milestone.

What Postgres holds today, in both environments:

- **bronze**: USGS events as loaded by dlt. USGS keeps its catalogue and serves
  it by `updatedafter`, so the rows can be fetched again. What a re-load does
  not bring back is earlier revisions of an event: the API returns its current
  version only.
- **silver and gold**: built by dbt from bronze, using each event's latest
  revision only, so they are rebuilt identically from a re-loaded bronze.
- **dlt's state tables**: rebuilt by the first run.
- **roles**: declared in the `Cluster` manifests; credentials are sealed in
  Git, and the Sealed Secrets key is backed up to 1Password
  ([ADR-0010](0010-sealed-secrets.md)).
- **staging's `lagom_dev`**: the developer's database, disposable by design
  ([ADR-0014](0014-develop-against-staging.md)); a developer's work there is
  lost with the node, and that is accepted. Out of scope here.

Nothing in Postgres exists only on the node.

## Requirements and constraints

- If the node is lost, no data that exists nowhere else is lost.
- No resident component and no configuration before it is needed
  (ADR-0012: no disabled backup block).
- The trigger can be checked by looking at the platform, not by judgement.

## Alternatives considered

**Keep the M2 timing and build the backup now.** It protects copies of data
USGS already keeps, and its cheapest form (`pg_dump` to R2) still adds an
external account, a credential and a schedule to maintain. Rejected for now: it
costs more than it protects.

**Drop the backup until M7.** Rejected: M3 (Dagster's run history) and M5 (a
streaming source, which is not replayable) both create state that exists only
on the node. Waiting for a milestone would let that state accumulate
unprotected.

## Decision

The backup is built when the first of these is true, whichever comes first:

1. **Postgres holds state that no source can rebuild** — Dagster's metastore
   (M3), a source that does not keep its history (the M5 streaming source), or
   any table written by hand or by a consumer.
2. **Someone other than the operator relies on the data** — the first
   external reader (M4, behind Cloudflare Access). Recovery time then matters
   to someone else, and a re-load is not a recovery-time guarantee. A login
   role in `gold_reader` for the operator's own tools (a report built in CI,
   for instance) does not fire this: its data is rebuilt as easily as gold.

Until then, recovery after losing the node is: rebuild from Git, then re-load
bronze from USGS with `initial_lookback_days` (`services/usgs/ingestion/source.yaml`)
set to cover the history wanted, then `dbt build`. **This procedure has not been
run.** The first run belongs to the disaster-recovery drill, which stays in M2
and measures its RTO.

## Consequences

**Positive.** No new account, credential, schedule or resident component while
there is nothing unique to protect. The trigger is stated in terms anyone can
check.

**Negative.**

- **The DR drill's recovery is a re-load, not a restore.** It tests rebuilding
  from Git and from the source. A restore from backup is tested when the backup
  exists.
- **Event revision history is not recoverable.** A re-load brings back each
  event's current version only. No model uses earlier revisions today.
- **The recovery relies on USGS.** If the API is down or changes when the node
  is lost, recovery waits for it.
- **The re-load is untested.** Paging deep into history through the API may hit
  limits not seen at a 30-day window. The DR drill is where this is found.

## Risks, cost, and reversal

No cost. The risk is that a trigger fires and nobody notices: the roadmap lists
the backup by its trigger, and the M3 and M5 items that would fire it name it.

Reversal: build the backup earlier, with the mechanism chosen as ADR-0012
describes. Nothing has to be undone.
