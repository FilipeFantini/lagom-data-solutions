# ADR-0025 — Postgres backup: the Barman Cloud plugin to Cloudflare R2, staging first

- **Status:** Accepted for staging; prod follows once a restore in staging has
  passed (see *How it is accepted*)
- **Date:** 2026-10-28
- **Decided by:** the operator, on 2026-10-28, choosing the plugin over a
  `pg_dump` job.
- **Implements:** the backup [ADR-0019](0019-postgres-backup-deferred.md)
  deferred until its trigger. Dagster's run history, next in M3, is that
  trigger. The mechanism is one of the options [ADR-0012](0012-cloudnative-pg.md)
  left open.

## Context and problem

Dagster keeps its run history in Postgres. That history exists only on the
node, so ADR-0019's trigger fires before Dagster enters. With the SME stack
([ADR-0023](0023-sme-stack-duckdb-on-ducklake.md), proposed) the DuckLake
catalog in Postgres becomes the other state to protect. Cloudflare R2 now
exists for the lake, so a destination off the node is available.

## Alternatives considered

**`pg_dump` from a CronJob to R2.** Nothing resident, one container, easy to
read. Rejected by the operator: a dump is a snapshot, so anything written
since the last run is lost, and the restore path is hand-written rather than
the operator's.

**The Barman Cloud plugin**, chosen. CloudNativePG's supported path since its
in-tree `barmanObjectStore` was deprecated: an operator plugin (CNPG-I) plus a
sidecar in each Postgres Pod. Apache-2.0, part of the CloudNativePG project.

## Decision

- **Continuous WAL archiving and daily base backups** of each Cluster, through
  the Barman Cloud plugin (chart `plugin-barman-cloud` 0.8.1, plugin v0.15.1),
  into one R2 bucket per environment: `lagom-staging-backups` now,
  `lagom-prod-backups` with prod. A base backup is a full copy, and WAL is every
  change after it, shipped as each segment closes (at most every 5 minutes).
  Together they allow a restore to any moment in the retention window: point-in-
  time recovery. Retention is 7 days in staging.
- **cert-manager** (chart 1.21.3) is installed with it. The plugin and the
  operator talk over TLS, and cert-manager issues those certificates.
  Nothing else uses it yet.
- **One token per bucket**, object read and write, scoped to that bucket. It
  is sealed in the environment's namespace ([ADR-0010](0010-sealed-secrets.md)),
  with the R2 endpoint, so the Cloudflare account ID stays out of this public
  repository. The sidecar reads the endpoint from `AWS_ENDPOINT_URL_S3`.
- **The budget check counts the sidecar.** It runs in every Postgres Pod but
  is declared on the `ObjectStore`, which `tools/resource_budget.py` did not
  read. It now adds the sidecar's request to each instance of a Cluster that
  names an ObjectStore, and fails if the sidecar declares no resources.

## How it is accepted

The plugin's issue
[#411](https://github.com/cloudnative-pg/plugin-barman-cloud/issues/411),
"does not work with R2", is open. The first report was a configuration error.
The later ones, about S3-compatible stores rejecting retention deletes, were
fixed in Barman 3.16.2, which v0.15.1 is well past. Nobody has confirmed R2 end
to end. The endpoint passed as `AWS_ENDPOINT_URL_S3` is also unverified here.
If the SDK ignored it, archiving would go to AWS and fail, and step 1 below
would show it. So this is accepted for prod only after staging shows, with commands
recorded in the runbook:

1. WAL archiving works: the Cluster reports `ContinuousArchiving` true.
2. A base backup completes.
3. **A restore works:** a new Cluster bootstraps from the bucket and holds
   staging's row counts.
4. Retention deletes an expired backup without error.

If R2 fails one of these, this ADR is revised before prod.

## Consequences

**Positive.** Losing the node no longer loses Postgres: the RPO (data that can
be lost) drops from "everything" to minutes. Restores use the operator's own
recovery bootstrap. The bucket is off the node, in another provider.

**Negative.**

- **Resident memory: about 160 MiB of requests** for cert-manager's three
  Pods, 32 for the plugin and 64 per Postgres instance for the sidecar.
  These are starting figures, corrected by measurement. Total requests go
  from 2,078 to 2,334 MiB of the 5.5 GB ceiling.
- **A failure to archive fills the volume.** Postgres keeps the WAL it could not
  archive, so a broken token or bucket shows as a growing volume and a Cluster
  condition, not as data loss. That is loud, but it needs watching until
  alerting covers it.
- **Two more components to upgrade**, and a third party's S3 compatibility
  under the backups.
- **The budget check changed**, a CI gate. The change only adds what it could
  not see before.

## Risks, cost, and reversal

Cost: R2's free tier (10 GB, 1 million writes a month). Databases of a few
hundred megabytes and a WAL segment every few minutes stay well inside it.

Reversal: remove `plugins` from the Cluster, then the ObjectStore and the
ScheduledBackup, then the two Applications. The bucket keeps what was written.
