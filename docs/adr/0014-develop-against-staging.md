# ADR-0014 — Develop against staging, with no local services

- **Status:** Accepted
- **Date:** 2026-10-16
- **Supersedes:** the `dev` environment of [ADR-0007](0007-three-environments.md)
  (local machine, throwaway `k3d` cluster), and the "`dev` runs a local
  Postgres" consequence of [ADR-0008](0008-postgres-for-all-layers.md)

## Context and problem

ADR-0007 made `dev` the operator's machine, and ADR-0008 gave it a local Postgres
of the node's major version. Neither exists yet. The operator does not want to
fill the machine with services — a database server, a container runtime for
`k3d` — and the node already runs Postgres under an operator that can create
another one cheaply.

The question is where development touches real data and a real database,
without weakening what staging is for: catching a bad change before prod.

## Requirements and constraints

- Nothing resident on the operator's machine beyond the code and the Python
  environments `uv` creates per project.
- Development runs the same Postgres major version and SQL dialect as prod
  (the reason ADR-0008 rejected DuckDB for `dev`).
- Developer experiments must not dirty the data staging uses to validate a
  change, and must never reach prod.
- No inbound port on the node ([`architecture.md`](../architecture.md) §10).

## Alternatives considered

**Local Postgres on the operator's machine** (ADR-0008). Rejected by the
operator: a service to install, upgrade, and keep running on a personal machine.

**Develop inside the staging pipeline's own database.** No extra setup, but
every experiment would change the data staging validates against, so a green
staging run would no longer mean anything.

**A third Postgres Cluster for development.** Clean isolation, at ~300 MiB of
resident memory for something used a few hours a week. Rejected on the budget.

## Decision

**Code stays on the operator's machine; data lives in staging.**

- The staging Postgres `Cluster` holds two databases: `lagom`, used only by
  staging's pipeline, and **`lagom_dev`**, the developer's. A second database in
  the same instance costs no extra resident memory. All of it is declared in
  Git, not run by hand:
  - the `lagom_dev` role as a managed role of the `Cluster`, with its password
    in a Sealed Secret ([ADR-0010](0010-sealed-secrets.md));
  - the `lagom_dev` database as a CloudNativePG `Database` object owned by that
    role;
  - a `pg_hba` rule on the `Cluster` rejecting `lagom_dev` on database `lagom`.
    Postgres grants every role CONNECT on every database by default, so the
    rule is what keeps the developer out of staging's data, not the ownership.
    It is verified when staging is built.
- The developer runs `dlt` and `dbt` from the machine, in the `uv` environment
  of the service, against `lagom_dev` through `kubectl port-forward` over the
  tailnet — the same private path `kubectl` already uses. Nothing is exposed on
  the node.
- `lagom_dev` is disposable: it can be dropped and recreated at any time.
- Unit tests stay on the machine and need no database: dlt tests use DuckDB
  in-process (`services/usgs/tests`).
- Manifest checks run as `kubectl apply --dry-run=server` against the real
  cluster, replacing the throwaway `k3d` cluster.

ADR-0007's isolation of staging from prod is unchanged: its own `Cluster`,
ResourceQuota and LimitRange, NetworkPolicy denying staging to prod, separate
secrets.

## Consequences

**Positive.**

- Nothing to install or run locally beyond `uv`.
- Development uses the exact Postgres build prod runs, on the same architecture.
- Staging's own data stays clean, because the developer works in another
  database.

**Negative.**

- **No VPS or no tailnet means no database work.** Unit tests still run offline.
- **Developer load lands on staging's Postgres.** A heavy query from `lagom_dev`
  slows staging's pipeline. It cannot reach prod: staging's ResourceQuota bounds
  it, as it bounds everything in that namespace.
- **The databases share one instance, so a superuser mistake can still cross
  them.** Administration goes through `kubectl exec`, as in prod; the developer
  role itself is not a superuser.

## Risks, cost, and reversal

No monetary cost, and no resident memory beyond staging's Postgres, which
ADR-0007 already budgeted.

**An inconsistency this decision does not resolve.** ADR-0007 says staging's
dlt and dbt run "as Kubernetes Jobs triggered by CI". CI runs on GitHub's
machines, which are not on the tailnet, and the node has no inbound port, so CI
cannot trigger anything in the cluster. How a change reaches staging before
prod is decided in [ADR-0015](0015-images-on-ghcr.md).

Reversal: install Postgres locally and point the developer's `uv` environment
at it. The trigger would be a second developer whose work collides with the
first one's in `lagom_dev`; at that point each developer gets a database of
their own in the same instance before anything heavier is considered.
