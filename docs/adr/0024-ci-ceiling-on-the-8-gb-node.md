# ADR-0024 — CI ceiling raised to 5.5 GB, measured on the 8 GB node

- **Status:** Accepted
- **Date:** 2026-10-28
- **Supersedes:** the 2.2 GB figure of [ADR-0016](0016-ci-ceiling-2-2-gb.md).
  Its method (overhead measured by RSS, ceiling below what is left) stands.

## Context and problem

The resource budget check fails a pull request whose declared memory requests
exceed the ceiling stated in [`architecture.md`](../architecture.md) §11.
ADR-0016 set 2.2 GB from the 4 GB node's measured overhead. On 2026-10-28 the
platform moved to `lagom-shared-02`, a CAX21 with 8 GB
([ADR-0020](0020-move-to-the-8-gb-node.md)), which said the new ceiling is
set by measuring the overhead on the new node, not derived by proportion.
Until then, M3's Dagster (600 MiB measured in
[ADR-0011](0011-memory-viability-on-4gb.md)'s spike) cannot merge.

## Measurement

On `lagom-shared-02`, 2026-10-28, with k3s running for about two hours and
12 Pods running (the full M2 platform, between pipeline runs), RSS read from
`/proc`:

| | MiB |
|---|---|
| Memory visible to the OS (`MemTotal`) | 7,741 |
| `k3s-server` (`GOMEMLIMIT=900MiB`; 115 garbage collections since start, so no thrash) | 1,022 |
| `containerd` | 200 |
| one `containerd-shim` per Pod, 12 | 254 |
| `tailscaled` | 55 |
| the rest of the OS (systemd, journald, sshd, unattended-upgrades, dhcpcd, …) | ~156 |
| **Outside Kubernetes, total** | **1,687** |
| Inside Kubernetes (all Pods, for reference) | 1,513 |

That leaves **~6,050 MiB** for Pods. RSS overstates shared pages, so it is
the conservative measure.

## Requirements and constraints

- The ceiling must be something the node can hold, with margin for what the
  measurement could not see.
- It must admit M3 as planned: Dagster and, at its trigger, the Postgres
  backup ([ADR-0019](0019-postgres-backup-deferred.md)).
- Frugal by design, not capped by the node
  ([`architecture.md`](../architecture.md) §1): room under the ceiling is not
  an allowance to spend.

## Alternatives considered

**~5.9 GB, the full measured room minus ADR-0016's 100 MB.** Rejected: the
measurement is two hours old. On the old node `k3s-server` kept growing for
days, and each new Pod adds a shim (about 20 MiB here) that requests do not
count. Dagster alone brings several Pods.

**Keep 2.2 GB until a longer measurement.** Rejected: it blocks M3 for no
reason the node shows. The overhead would have to more than double to make
5.5 GB unsafe.

## Decision

**Ceiling enforced in CI: 5.5 GB of declared requests** (5,632 MiB), about
420 MiB under the ~6,050 MiB the measurement leaves. That margin is for
k3s's growth over days and for the shims of the Pods M3 adds.

Against it, with the budget check's own accounting (resident requests, the
CoreDNS allowance, every ephemeral job at once):

| Point | Requests | Margin |
|---|---|---|
| 2026-10-28 (M2 platform) | 2,078 MiB | +3,554 MiB |
| M3, adding Dagster at 600 MiB | ~2,680 MiB | ~+2,950 MiB |

## Consequences

**Positive.** M3 fits with room for the backup's resident cost. The check
again states what the node holds.

**Negative.** A ceiling this far above use catches only large mistakes. It
does not stop many small additions. Keeping requests honest stays the job of
review, as §16.5 of the engineering protocol already says.

## Risks, cost, and reversal

No cost. The risk is that the overhead grows past the margin over days of
uptime. **Re-measure after at least three days of uptime**, with the same
reading, and record the result as a note here. Reversal: one number in §11,
changed with a new measurement.
