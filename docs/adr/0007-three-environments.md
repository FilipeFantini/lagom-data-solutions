# ADR-0007 — Three environments: dev local, staging and prod on one node

- **Status:** Accepted — partially superseded by [ADR-0008](0008-postgres-for-all-layers.md)
  (the `dev` environment's storage only) and by
  [ADR-0014](0014-develop-against-staging.md) (the `dev` environment as a whole), and by
  [ADR-0015](0015-images-on-ghcr.md) (what triggers staging's jobs), and by
  [ADR-0026](0026-dagster-one-instance-per-environment.md) ("staging runs no
  Dagster": each environment now runs its own)
- **Note:** the 2.6 GB ceiling cited below was lowered to 2.2 GB by
  [ADR-0016](0016-ci-ceiling-2-2-gb.md)
- **Date:** 2026-10-12

## Context and problem

The platform is deployed by Argo CD from this repository. Promotion only means
something if there is somewhere to promote from, so the environment question has
to be answered before the first deployment, not after.

The constraint is one 4 GB node with a resident budget of 2.6 GB. A second VPS
would double the monthly cost and break the premise the project exists to prove.

The objection that shaped this decision: **staging that shares a database with
prod is theatre.** A pipeline that passes against prod data in a neighbouring
namespace proves nothing and grants false confidence.

## Requirements and constraints

- Promotion must test something real: a manifest that fails to sync, a migration
  that breaks, a dbt model that fails, a missing secret, an image that does not
  run on arm64, an ingress that cannot obtain a certificate.
- A staging failure must not be able to damage or starve prod.
- Resident footprint must stay under the declared ceiling.
- One operator today, two developers later.

## Alternatives considered

**Two environments: dev local, prod on the node.** Simplest, and it was the
first answer. Rejected because there is then nowhere to catch a bad manifest or
a broken migration before it reaches the only environment that exists.

**Staging as a bare namespace sharing prod's Postgres.** Cheapest form of
"three environments" and the one worth naming explicitly as rejected: shared
state means a staging run can read or corrupt prod data, and resource contention
is unbounded. This is the theatre the requirement above rules out.

**Ephemeral staging, created and destroyed by CI per pull request.** Costs zero
resident RAM and proves the environment builds from nothing. Rejected on two
practical grounds raised in review: an environment that is destroyed on failure
takes the failure state with it, making diagnosis harder; and there is no
standing URL to point a browser at before promoting.

**A second VPS.** Real isolation, including from node failure. Deferred: it
doubles cost for a platform with no users, and a small second VPS would not
meaningfully test node failure anyway — that needs actual HA.

## Decision

Three environments:

**`dev` — the operator's own machine.** dbt and dlt run against a local DuckDB
file and a `dev/` prefix in the bucket. This covers most day-to-day work and
needs no cluster. When a manifest, Argo CD behaviour, or RBAC needs testing, a
throwaway `k3d` cluster is created locally and deleted afterwards.

**`staging` — a permanent, deliberately thin namespace on the node.** Four
conditions make it real rather than nominal, and without them this decision
would not hold:

1. **Its own Postgres** — a separate pod, database, and credentials. Never
   prod's instance.
2. **ResourceQuota and LimitRange** on the namespace, so starving prod is
   prevented by the kubelet rather than by good intentions.
3. **NetworkPolicy denying staging → prod.** If a staging job can reach prod's
   Postgres, the isolation is fictional.
4. **Separate secrets.** A staging credential opens nothing in prod.

**`prod` — the permanent namespace** on `lagom-prod-01`.

**Staging runs no Dagster.** The orchestrator is the heavy component at ~600 MB;
two of them exceed the ceiling. In staging, dlt and dbt run as Kubernetes Jobs
triggered by CI. Budget: ~1.8 GB for prod plus ~300 MB for staging's Postgres =
~2.1 GB against a 2.6 GB ceiling.

**Staging is recreated on demand, before structural infrastructure changes** — a
k3s upgrade, an Argo CD change, a new component — and not on a schedule. A
weekly rebuild was considered and rejected: the thing it would test, building
from nothing, is tested better by the prod disaster-recovery drill in M2, which
rebuilds from Git plus the latest backup and measures real RTO. A rebuild
cadence with no requirement behind it is ritual.

## Consequences

**Positive.** Promotion tests manifests against a real cluster with real Argo CD
and a real database. Cost stays at one VPS. Staging has a standing URL and keeps
its state when something breaks, which is when state matters most.

**Negative, stated plainly:**

- **No isolation from node failure or global memory pressure.** A kernel OOM or
  a reboot takes both environments. This is a cost decision, not an oversight.
- **Dagster configuration is not exercised in staging.** A badly defined asset
  surfaces first in prod. Partially mitigated because Dagster's configuration is
  a manifest, and a broken manifest is rejected at sync.
- **Staging accumulates drift** between on-demand rebuilds — stale test data, a
  migration applied out of order. Accepted with one operator; it is the first
  thing to revisit with more.

## Risks, cost, and reversal

Reversal is straightforward and the trigger is known: **a real client.** At that
point a second VPS makes the premise "EUR 10/month with isolated environments",
which is still far below any managed alternative. Nothing in this decision has
to be undone to get there — the overlays and the namespace split carry over to a
second cluster unchanged.

The residual risk to watch: if prod and staging ever contend for memory in
practice, the ResourceQuota was set wrong. That is a tuning problem, not a
design one, but it will look like a design problem when it happens.

## Notes after acceptance

The text above is kept as accepted. These notes record what changed since,
without rewriting it.

- **2026-10-12 — host name.** The node was provisioned as `lagom-shared-01`,
  not `lagom-prod-01`: it hosts both the prod and the staging namespace, so
  naming it after one environment was wrong. `lagom-prod-01` is left for a
  dedicated prod node, whose trigger is still a real client. The decision is
  unchanged.
- **2026-10-12 — `dev` storage.** `dev` runs dbt and dlt against a local
  Postgres instead of a DuckDB file and a bucket prefix — see
  [ADR-0008](0008-postgres-for-all-layers.md).
- **2026-10-12 — budget re-measured.** The ~1.8 GB figure above counted k3s at
  300 MB; measured, the overhead outside Kubernetes is ~0.95 GB. Counted as pod
  requests against the 2.6 GB ceiling, prod's core plus staging's Postgres is
  ~1.75 GB, leaving ~0.85 GB for jobs instead of the margin implied above. The
  decision still fits; the margin is thinner. See
  [`architecture.md`](../architecture.md) §11.
- **2026-10-12 — price confirmed.** The node costs EUR 7.37/month
  ([ADR-0002](0002-single-node-k3s-hetzner.md)), so the reversal premise above
  reads roughly "EUR 15/month with isolated environments".
