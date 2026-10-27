# ADR-0016 — CI ceiling lowered to 2.2 GB from the measured overhead

- **Status:** Accepted
- **Date:** 2026-10-17
- **Supersedes:** decision 3 of [ADR-0011](0011-memory-viability-on-4gb.md)
  ("the 2.6 GB ceiling stands")

## Context and problem

The resource budget check fails a pull request whose declared memory requests
exceed a ceiling stated in [`architecture.md`](../architecture.md) §11. The
ceiling was 2.6 GB, derived in M1 from the node's 3.8 GB minus ~1.1 GB of
overhead outside Kubernetes, and kept by ADR-0011.

On 2026-10-17 the overhead measured ~1.5 GB by RSS (ADR-0011 notes): k3s grew
with the cluster and its memory limit was raised from 600 to 900 MiB to stop a
garbage-collection thrash, and containerd holds one shim per running pod. So
3.8 − 1.5 leaves ~2.3 GB for pods, and the check was allowing 2.6 GB. A gate
that permits more than the node can hold is the false confidence
[ADR-0013](0013-agent-driven-development-guardrails.md) rule 5 warns against.

## Requirements and constraints

- The ceiling must be something the node can actually hold, with margin.
- It must not block M2, which is in progress.
- The 4 GB node is today's choice, not a cap on growth: moving to the 8 GB node
  stays the answer when a planned component cannot fit
  ([ADR-0011](0011-memory-viability-on-4gb.md) decision 4).

## Alternatives considered

**Keep 2.6 GB and rely on the node's available memory.** Nothing breaks today
(1.5 GB declared, 1.6 GB available). Rejected: the check would stop meaning
what it says, and the first time it mattered it would pass a change that does
not fit.

**Lower to 2.3 GB, the full measured room.** Rejected: no margin, and RSS is
the conservative measure only on its own terms — a component added to the node
also adds a shim and grows k3s.

**Move to the 8 GB node now.** Rejected by the operator for now: M2 fits, and
the move is made when a component does not, not in anticipation.

## Decision

**Ceiling enforced in CI: 2.2 GB of declared requests**, about 100 MB under the
~2.3 GB the measured overhead leaves. RSS overstates shared pages, so the real
margin is larger than that.

Projected against it, with the budget check's own accounting (resident
requests, k3s built-ins, and the largest ephemeral job):

| Point | Requests | Margin |
|---|---|---|
| 2026-10-17 | 1,522 MiB | +731 MiB |
| End of M2, a ~300 MiB dlt/dbt CronJob as the largest job | ~1,790 MiB | +463 MiB |
| M3, adding Dagster at the 600 MiB measured in ADR-0011's spike | ~2,390 MiB | **−137 MiB** |

**M3 does not fit as planned.** By the operator's rule (2026-10-17), the move to
the 8 GB node is decided when M3 or M5 does not fit under the ceiling. So it is
expected at M3, unless Dagster's real requests, measured then, come in about
150 MiB under the spike's projection.

## Consequences

**Positive.** The check means what it says again. The M3 consequence is known
now rather than discovered when Dagster's pull request turns red.

**Negative.** Less room for experiments on this node: the full design (NATS,
Streamlit, Grafana) no longer fits at all, as §11 already said. The ceiling has
to be revisited whenever the overhead is measured again.

## Risks, cost, and reversal

No cost. The risk is the opposite error: a ceiling set too low blocks a change
that would fit. The reversal is one number in §11, changed with a new
measurement.

## Notes after acceptance

The text above is kept as accepted. These notes record what changed since,
without rewriting it.

- **2026-10-19 — the check counts every ephemeral job at once.** The table
  above used the largest job only. Staging's and prod's pipeline CronJobs
  share a schedule, so both Pods run together every 30 minutes, and the
  largest-job count under-stated that peak by 256 MiB. Counted as a sum, the
  end of M2 is 2,034 MiB (+219 MiB), and M3 with Dagster at 600 MiB would be
  about 2,630 MiB (about −380 MiB). The conclusion stands and grows firmer:
  M3 does not fit on this node as planned.
