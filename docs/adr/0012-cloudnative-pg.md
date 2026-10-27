# ADR-0012 — CloudNativePG runs Postgres; backup mechanism chosen at its trigger

- **Status:** Accepted
- **Date:** 2026-10-16

## Context and problem

M2 needs Postgres in the cluster: every layer lives there
([ADR-0008](0008-postgres-for-all-layers.md)), and later it is also Dagster's
metastore. Nothing so far decides *how* it runs. The choice shapes how the
database is declared, how credentials and roles are managed, how it is backed
up and restored, and how much resident memory it costs on a node whose margin
is about 1 GB ([ADR-0011](0011-memory-viability-on-4gb.md)).

## Requirements and constraints

- Declared in Git and reconciled by Argo CD like everything else
  ([ADR-0009](0009-argocd-bootstrap-and-self-management.md)).
- Credentials never in plain text in Git ([ADR-0010](0010-sealed-secrets.md)).
- A credible path to production practice: backup to object storage,
  point-in-time recovery, declarative roles, connection pooling — available
  when their triggers arrive, without replacing the database layer.
- Every resident process states its memory cost
  ([`engineering-protocol.md`](../engineering-protocol.md) §16.5).

## Alternatives considered

**A plain StatefulSet with the official `postgres` image.** Four manifests
(StatefulSet, Service, PVC, Secret) and zero resident overhead beyond Postgres
itself. Rejected: backup, restore, role management, and upgrades become scripts
we write and maintain, and none of it is how Postgres is run on Kubernetes in
production. It teaches the primitives but leaves the platform a step behind the
practice it is meant to demonstrate.

**A Helm chart wrapping a StatefulSet (e.g. Bitnami's).** Same model as above
with more knobs. Rejected for the same reasons, plus Bitnami's 2025 change to
its free image catalogue makes it a fragile dependency.

**Other operators (Zalando, Crunchy PGO).** Comparable features. Rejected:
Zalando's depends on Patroni and Spilo images with a heavier footprint, and
Crunchy's free distribution has licensing caveats on its images. CloudNativePG
is a CNCF project under Apache 2.0, with no paid tier needed for any feature
used here.

## Decision

**CloudNativePG**, chart `cloudnative-pg` 0.29.1 (operator 1.30.1), in
`cnpg-system`, managed by Argo CD from
[`platform/infra/cloudnative-pg/values.yaml`](../../platform/infra/cloudnative-pg/values.yaml).

How it works: the chart installs **CRDs** (Custom Resource Definitions — new
object kinds such as `Cluster`, `Database`, `Pooler`) and a controller, the
**operator**. We commit a `Cluster` object that says what we want — Postgres
version, instances, disk, resources, roles — and the operator creates the Pods,
PVCs, Services, and Secrets to match, then keeps them matching. It is the same
reconciliation loop as Argo CD, specialised in Postgres. It does not use a
StatefulSet; it manages Pods and PVCs directly, so it can control failover and
upgrades itself.

Three settings follow from this node:

1. **`GOMEMLIMIT` on the operator** — it is a resident Go process
   ([ADR-0011](0011-memory-viability-on-4gb.md) decision 2).
2. **Server-Side Apply in Argo CD.** The `clusters` and `poolers` CRDs render to
   470 KB and 679 KB. Client-side apply stores a copy of each object in an
   annotation limited to 256 KiB, so it would fail; server-side apply does not
   keep that copy.
3. **Pruning off.** Deleting the `Cluster` CRD deletes every database with it.
   The chart marks its CRDs with Helm's `resource-policy: keep`, which Argo CD
   honours when the Application is deleted but not on prune — so a chart
   upgrade that dropped a CRD would remove it. A removal must never be one
   merge away.

### Backup: deferred, no placeholder

The roadmap already brings backup in at the end of M2, when there is real data.
Until then **no backup configuration exists** — not a disabled one. A disabled
block reads as protection that is not there, and would be written against an
API that is changing (below).

When the trigger arrives, the mechanism is chosen among these, measured on the
node:

| Option | Resident cost | Recovery |
|---|---|---|
| Barman Cloud Plugin to R2 | a plugin Deployment, plus **cert-manager**, which the plugin requires | point-in-time (WAL archive) |
| In-core `barmanObjectStore` to R2 | none beyond the operator | point-in-time — but deprecated since operator 1.26, with no removal version announced |
| `pg_dump` CronJob to R2 | none (ephemeral job) | to the last dump only |

The plugin is the supported path, and its cost — two more resident components —
is exactly what [ADR-0011](0011-memory-viability-on-4gb.md)'s margin has to
absorb. That is why it is measured then, not assumed now.

## Consequences

**Positive.**

- A database is ~20 lines of YAML; the operator owns the mechanics.
- Roles, databases, and a PgBouncer pooler are declarative objects (`Cluster`
  managed roles, `Database`, `Pooler`) when their triggers arrive — no new tool.
- Backup, point-in-time recovery, and minor upgrades are operator features
  rather than scripts we maintain.

**Negative.**

- **One more resident process.** The operator's memory is measured at install
  and recorded in [`architecture.md`](../architecture.md) §11.
- **Each Postgres pod runs CloudNativePG's instance manager as PID 1**, a Go
  process supervising Postgres. Its cost is measured with the first `Cluster`.
- **More to learn and more indirection.** Debugging goes through the operator's
  status and logs before reaching Postgres. The runbook has to cover it.
- **The operator holds cluster-wide permissions** (chart default
  `clusterWide: true`): read and write on Secrets in every namespace — the
  Argo CD admin secret and the Sealed Secrets key included — `pods/exec`, and
  creating Roles and RoleBindings. A compromised or buggy operator reaches all
  of it. Accepted for now: the operator is a widely reviewed CNCF project and
  there is one databases namespace. The alternative, `clusterWide: false` with
  `WATCH_NAMESPACE` limited to the database namespaces, is revisited when the
  `staging` namespace arrives in M2.
- **The webhook fails closed** (`failurePolicy: Fail`): while the operator is
  down, `Cluster` objects cannot be created or changed. Running databases are
  unaffected.
- **The 11 CRDs, two of them large, add to what Argo CD's controller caches**
  ([ADR-0011](0011-memory-viability-on-4gb.md)). Measured at install.

## Risks, cost, and reversal

No monetary cost: the operator is open source and runs on the existing node.

Reversal: `pg_dump` from the operator's cluster, restore into a plain
StatefulSet, then remove the `Cluster` objects and the operator, CRDs last. At
megabytes of data this is minutes. The trigger would be the operator's memory
breaching the fallback criteria in ADR-0011 on its own, or an upgrade path that
CloudNativePG stops supporting.

## Notes after acceptance

The text above is kept as accepted. These notes record what changed since,
without rewriting it.

- **2026-10-17 — cluster-wide RBAC revisited, kept.** The revisit promised for
  the arrival of `staging` was done. The chart (0.29.1) cannot scope the
  operator to `prod` and `staging`: `clusterWide: false` limits it to its own
  namespace, so watching two namespaces would mean overriding
  `WATCH_NAMESPACE` and committing hand-copied Roles in each of them. Those
  copies would drift silently from the chart's rules on every upgrade — a
  narrower control that fails quietly, traded for a broad one the chart
  maintains. Kept cluster-wide. Revisit when a namespace holds credentials
  beyond the platform's own (a client's data), or when the chart supports a
  list of watched namespaces.

