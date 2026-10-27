# ADR-0018 — Pipeline liveness by heartbeat to Healthchecks.io

- **Status:** Accepted
- **Date:** 2026-10-27

## Context and problem

On 2026-10-27 the USGS pipeline failed in both environments for about 90
minutes: three events arrived with their status in capitals, and a dbt test
stopped every run. The failure was loud inside the cluster — Jobs failed, Argo
CD showed `Degraded` — and nobody was told. It was found because someone
happened to look.

"Fail loudly" ([`CLAUDE.md`](../../CLAUDE.md) §3) only holds if the noise reaches
a person. Today nothing leaves the cluster when a run fails or stops running.
Dagster's native alerting (M3) is the planned answer, but M3 does not fit the
4 GB node ([ADR-0016](0016-ci-ceiling-2-2-gb.md)), so it cannot be the answer
now.

The node accepts no inbound connection
([`architecture.md`](../architecture.md#tailscale-acl-and-zero-inbound-ports-m1)),
so a monitor that probes a URL from outside has nothing to probe.

## Requirements and constraints

- A person is told when a pipeline run fails, when it stops being scheduled,
  and when the node or the cluster is down — without opening a port.
- No change to the resident memory budget
  ([`architecture.md`](../architecture.md#11-resource-budget) §11).
- No monetary cost.
- The signal must not be fakeable from the public repository.
- Each environment alerts on its own.

## Alternatives considered

**An uptime monitor that polls a URL (UptimeRobot's HTTP monitor).** Its free
plan is the usual choice for this, and it is what the operator used in another
project. Rejected: it needs something reachable from the internet, and nothing
is. UptimeRobot's cron/heartbeat monitors are the right model, but its own
comparison page places them on paid plans; third-party listings disagree, so
it was not relied on.

**Self-host Healthchecks or Uptime Kuma in the cluster.** No external
dependency. Rejected: a resident process (tens of MiB) against a budget with
~220 MiB left, and a monitor that lives on the node it monitors goes silent
together with it — the one failure it most needs to report.

**Grafana alerting.** Already listed with its trigger and 150 MB
([`architecture.md`](../architecture.md#9-visualization)). Rejected for now:
150 MB resident, and it would still need a way to reach a person.

**The Job sends e-mail itself on failure.** Rejected: SMTP credentials in the
cluster, and a run that never starts — the controller down, the node off —
sends nothing.

**A heartbeat to Healthchecks.io.** Chosen.

## Decision

1. **Each successful run pings a check; a missing ping is the alarm.**
   Healthchecks.io knows each check's schedule. If no ping arrives within the
   schedule plus a grace period, it e-mails the operator. One check per
   environment: `lagom-usgs-staging` and `lagom-usgs-prod`.
2. **Schedule `*/30 * * * *` (UTC), grace 20 minutes.** A run may start up to
   5 minutes late (`startingDeadlineSeconds: 300`) and lasts at most 15
   (`activeDeadlineSeconds: 900`, retry included), so 20 minutes is the latest
   a healthy run can ping. The worst case from failure to e-mail is about 50
   minutes.
3. **The ping runs only after the pipeline succeeded.** `transform` moves from
   a regular container to the second init container, after `ingest`; a new
   regular container, `heartbeat`, sends the ping. The kubelet starts regular
   containers only when every init container exited 0, so a failed load or a
   failed dbt test means no ping — enforced by Kubernetes, not by a script.
4. **The heartbeat reuses the `lagom-warehouse` image** with its command
   overridden to a few lines of Python's standard library: no new image, no
   new digest to promote. It tries three times, ten seconds each, then exits 1
   so the Pod fails loudly; it never prints the URL.
5. **The ping URL is a secret.** Anyone who has it can send a success and
   silence the alarm. It is a SealedSecret per namespace,
   `pipeline-heartbeat` with key `url` ([ADR-0010](0010-sealed-secrets.md)).
6. **The account and the checks are created by hand** in Healthchecks.io's
   console, like the other resources outside the cluster
   ([`architecture.md`](../architecture.md#3-infrastructure)).

## Consequences

**Positive.**

- A failed run, a run that never starts, a stopped CronJob controller, a dead
  node, and a dead Postgres all end in the same missing ping, so one mechanism
  covers them.
- Nothing resident is added. The Pod's memory request stays 256Mi: a Pod
  requests the larger of its biggest init container and the sum of its regular
  containers, and `heartbeat` asks for 32Mi.
- No port is opened; the ping is an outbound HTTPS request, like `ingest`'s
  call to USGS.

**Negative.**

- **Alerts are slow by design.** Up to ~50 minutes from failure to e-mail. A
  `/fail` signal would make failures immediate, but a failed init container
  stops the Pod before any container could send it.
- **A third party sits in the alert path.** If Healthchecks.io is down, alerts
  stop with it — silently. Its code is open source (BSD), so self-hosting it
  off the node is the exit.
- **A failing ping fails the run.** With `backoffLimit: 1` the second Pod runs
  `ingest` and `transform` again before retrying the ping. That repeats work,
  not data: dlt merges on `(id, updated)` and dbt rebuilds its tables.
- **The free plan's limits were read on third-party listings** (20 checks),
  not on Healthchecks.io's own page; checked again when the account is made.
- **The pipeline's container layout changes**: `transform` logs are now an
  init container's, and the runbook's Pod states change with it.

## Risks, cost, and reversal

No monetary cost on the free plan. Two checks of twenty.

The main risk is an alert nobody reads. The e-mail goes to the operator's
account address; whether it reaches a phone is the operator's setting, outside
this repository.

Reversal: delete the `heartbeat` container and the two sealed files, move
`transform` back to a regular container, and delete the checks. Dagster's
alerting (M3) is expected to supersede this decision; the trigger to revisit
is M3 starting.
