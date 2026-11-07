# ADR-0033 — Dagster raises the alarm: a failure sensor and a heartbeat, both through Healthchecks.io

- **Status:** Proposed
- **Date:** 2026-11-07
- **Amends:** in [ADR-0026](0026-dagster-one-instance-per-environment.md),
  *Heartbeat*: "native failure alerting or a ping after each successful run"
  becomes both, through one check.

## Context and problem

The CronJobs on Postgres can be retired from 2026-11-12, but only once Dagster
has taken over the alarm ([ADR-0026](0026-dagster-one-instance-per-environment.md)).
Today the only alarm is the CronJob's heartbeat to Healthchecks.io
([ADR-0018](0018-pipeline-heartbeat.md)). Dagster's runs are watched in its
UI, which tells nobody.

Two kinds of failure have to reach the operator:

- **A run fails.** It should be reported at once, with the error.
- **Nothing runs.** The daemon, the code server, the node or the cluster is
  down. Nothing inside the cluster can report this, because it is down too.

Native alerting answers the first and is silent on the second: it runs on the
node it watches. A heartbeat answers the second, but only after the schedule
plus the grace period has passed, and it says nothing about why.

## Requirements and constraints

- Both kinds of failure reach a person, without opening a port.
- No change to the resident memory budget
  ([`architecture.md`](../architecture.md#11-resource-budget) §11).
- No monetary cost; no SMTP or chat credentials in the cluster.
- Each environment alerts on its own.
- While the CronJobs still run, an alarm from one pipeline must not be masked
  by the other's success.

## Alternatives considered

**Dagster's native alerting alone** (a run-failure sensor sending e-mail or a
chat message). Rejected: it needs an SMTP or chat credential in the cluster
([ADR-0018](0018-pipeline-heartbeat.md) rejected the same for the Job), and it
says nothing when the daemon or the node is down.

**A success ping alone,** as the CronJob does. Rejected: a failed run is
reported only when its ping is late, up to about 50 minutes later, and without
the error.

**Reuse the CronJob's check (`lagom-usgs-<env>`).** No new secret. Rejected:
while both pipelines run, the CronJob's success would clear a Dagster failure,
and the alarm could only be tested in an environment once its CronJob was gone.

## Decision

1. **One new check per environment,** `lagom-dagster-staging` and
   `lagom-dagster-prod`, schedule `*/30 * * * *` (UTC). The grace period starts
   at 20 minutes and is set from the longest run measured in staging, plus the
   queue delay, before prod's check goes live.
2. **A run-status sensor pings the check after each successful run** of the
   USGS job. A missing ping is the alarm for "nothing runs", as in ADR-0018.
3. **A run-failure sensor calls the check's `/fail` endpoint** for any failed
   run in the code location, with the job name, the run ID and the error in the
   request body (truncated to stay under Healthchecks.io's limit). Healthchecks
   e-mails at once. The next successful run clears it.
4. **Both sensors run in the code location,** which already runs all the time.
   No new process, no new image.
5. **The ping URL is a secret,** as in ADR-0018: whoever has it can silence the
   alarm. A SealedSecret per namespace, `dagster-heartbeat`, key `url`,
   exposed only to the code server as `HEARTBEAT_URL`. Run Pods do not get it.
   The sensors never print the URL. A missing variable fails the code location
   at load, loudly.
6. **A ping that cannot be sent fails the sensor tick** after three attempts;
   Dagster shows the failed tick, and the missing ping raises the alarm anyway.
7. **When the CronJobs are retired,** check `lagom-usgs-<env>` and the Secret
   `pipeline-heartbeat` are deleted with them, in the same change. The number
   of sealed secrets per environment is then back to what it is today.

## Consequences

**Positive.** A failed run is reported within a minute, with its error. A
silent cluster is still reported by the missing ping. The alarm can be tested
in staging now, without touching the CronJobs.

**Negative.**

- **One more sealed secret per environment** until the CronJobs go.
- **One more check to keep** in the Healthchecks.io account, which has free
  room for it.
- **A failure in any job,** compaction included, marks the environment's check
  down until the next successful USGS run. That is deliberate: the check means
  "this environment's pipeline is healthy".

## Risks, cost, and reversal

Cost: none. The code server's memory does not change measurably; the sensors
are a few HTTP calls every 30 minutes.

Risk: a sensor that is turned off sends nothing. The success sensor's silence
is caught by the missing ping; the failure sensor's is not. Both are declared
with `default_status=RUNNING` and a test asserts it.

Reversal: remove the two sensors and the Secret; the CronJob's heartbeat keeps
running until it is retired.
