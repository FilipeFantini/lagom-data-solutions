# ADR-0011 — Memory viability on the 4 GB node, measured before M2

- **Status:** Accepted — decision 3 (the 2.6 GB ceiling) superseded by
  [ADR-0016](0016-ci-ceiling-2-2-gb.md)
- **Date:** 2026-10-13

## Context and problem

RAM is the constraint this platform is designed against
([`architecture.md`](../architecture.md) §1, §11). Two measurements in M1 had
already broken estimates: k3s used three times its quoted 300 MB, and Argo CD's
controller approached its limit within minutes. The question had to be answered
before building further, not after: **does the planned stack — k3s, Argo CD,
Postgres, Dagster — fit on 4 GB with room left for data jobs, or does it need a
bigger node or a different stack?** Discovering the answer in M3 would mean a
rewrite.

## Requirements and constraints

- Keep the stack whose learning value is the point of the project: Kubernetes
  (k3s), GitOps with a UI (Argo CD), and Dagster.
- Answer with measurements on this node, not vendor figures.
- Leave enough room for ephemeral jobs that the platform is still credible as
  production-grade, not a demo that runs only when nothing else does.

## Method

A spike on 2026-10-13, on the node itself:

1. Read the Go runtime's own metrics from k3s (`kubectl get --raw /metrics`),
   then set `GOMEMLIMIT` and sample for hours.
2. Install Dagster 1.13.26 temporarily in a scratch namespace — webserver,
   daemon, a code server, Postgres 17 as metastore — measure idle and during two
   real runs launched through its API, then delete it.
3. Measure, in a throwaway pod on the node, the memory cost of importing the
   libraries the real code server will load: dlt, dbt-core, dagster-dlt,
   dagster-dbt.

## Findings

**k3s held memory it was not using.** After 17 hours the `k3s-server` process
had grown from 627 MB to 1,235 MB of RSS, yet the Go runtime reported only
421 MiB of live heap: with no memory limit, Go lets the heap reach twice its
live size before collecting and keeps idle memory from the OS. With
`GOMEMLIMIT=600MiB` the same process ran at ~720–735 MiB over the first
half-hour, its runtime footprint (`sys`) holding at ~615 MiB instead of
1,173 MiB.

**Dagster is within its estimate:**

| Process | Idle | After runs |
|---|---|---|
| webserver | 128 MiB | 133 MiB |
| daemon | 114 MiB | 200 MiB (Python rarely returns memory) |
| code server, minimal definitions | 98 MiB | 153 MiB peak while loading |
| code server, real libraries (projected) | ~215 MiB | — |
| run pod (ephemeral) | — | 192 MiB minimal; ~250–300 MiB with dlt and dbt |

Importing the real libraries costs ~115 MiB on top of Dagster itself (63 →
177 MiB). Resident Dagster with real code is therefore **~550 MiB**, against
the 600 MB estimate.

**Argo CD's controller caches every object in the cluster**, so its memory
grows with everything installed, not only with what it manages: it rose to
505 MiB while the spike was installed.

### Projected M3 node

| Part | Memory | Source |
|---|---|---|
| Outside Kubernetes: k3s (with `GOMEMLIMIT`), containerd and shims, tailscaled, OS | ~1.1 GB | measured |
| kube-system pods and Sealed Secrets | ~0.1 GB | measured |
| Argo CD | ~0.5 GB | measured |
| Dagster, resident | ~0.55 GB | measured + projected imports |
| Postgres, prod | ~0.3 GB | estimate — measured under dbt load in M2 |
| Postgres, staging | ~0.2–0.3 GB | estimate |
| **Total** | **~2.75 GB of 3.8 GB** | |
| **Left for ephemeral jobs and page cache** | **~1 GB** | |

About three run pods of 250–300 MiB fit at once; in practice runs are
sequential at this data volume.

## Decision

1. **Keep the stack.** k3s, Argo CD, and Dagster fit, with ~1 GB left for jobs.
   Flux and Talos were considered and dropped: neither saves enough to justify
   losing the Argo CD UI or the k3s simplicity
   ([ADR-0002](0002-single-node-k3s-hetzner.md)).
2. **Every resident Go process runs with `GOMEMLIMIT`** — k3s and Argo CD's
   controller now. It is the largest lever found: it turned 1.2 GB into
   ~0.7 GB on k3s without changing anything else.
3. **Requests for Dagster are set from these numbers in M3**, and the CI check
   keeps the sum under the ceiling. The 2.6 GB ceiling stands.
4. **Fallback: a CAX21 (8 GB)**, decided on any of these, observed rather than
   anticipated:
   - available memory on the node stays under ~500 MiB in normal operation,
     or a platform component is OOM-killed or evicted;
   - a planned component cannot fit under the ceiling after tuning;
   - fitting requires removing what makes the platform production-grade —
     staging, backups, monitoring — rather than tuning it.

## Consequences

**Positive.** The roadmap continues with the stack it was designed around, and
the budget for M3 rests on measurements. The `GOMEMLIMIT` finding is cheap,
general, and reversible.

**Negative.**

- **The margin is about 1 GB, not more.** The full design's additions
  (Streamlit, Grafana, NATS with Redpanda Connect, ~0.5 GB together) would
  leave ~0.5 GB, which is the fallback's territory. They enter by trigger and
  are measured when they do.
- **Two figures are still estimates:** Postgres under dbt load (M2) and the
  real code server (M3).
- **`GOMEMLIMIT` trades CPU for memory.** Near the limit the garbage collector
  runs more often. CPU is idle most of the time on this node, and the limit sits
  ~40% above the measured live heap.

## Risks, cost, and reversal

The k3s figure with `GOMEMLIMIT` was observed for under an hour when this was
written; the 17-hour growth that exposed the problem must not reappear. Confirming it over 24 hours
is an open roadmap item.

Reversal of the `GOMEMLIMIT` setting is deleting one systemd drop-in. Moving to
the CAX21 is a resize with one reboot ([ADR-0002](0002-single-node-k3s-hetzner.md))
and roughly doubles the node's cost.

## Notes after acceptance

The text above is kept as accepted. These notes record what changed since,
without rewriting it.

- **2026-10-17 — `GOMEMLIMIT=600MiB` on k3s became a CPU problem; raised to
  900MiB.** The negative consequence this ADR named, "near the limit the garbage
  collector runs more often", happened. After the staging `Cluster` and prod's
  NetworkPolicy arrived, the k3s runtime held 719–753 MiB against its 600 MiB
  limit, ran ~5 collections per second (about 20 times its four-day average),
  and used ~1.9 of the node's 2 vCPU while every pod together used 27m. Raised to
  900MiB: CPU fell to 144m and collections to 0.3 per 10 s. Goroutines were
  ~8,600 both before and immediately after the restart, so this is the cluster's
  size, not a leak; it is being watched for 24 h to confirm. The limit is now
  ~44% above heap in use plus goroutine stacks (572 + 53 MiB, measured after
  the change) — close to this ADR's original ~40% — and must be rechecked whenever the
  cluster gains components. It was found by chance in a post-deploy check, an
  escape under [ADR-0013](0013-agent-driven-development-guardrails.md) rule 1.
- **2026-10-17 — the overhead outside Kubernetes is ~1.5 GB, not ~1.1 GB.**
  Measured by RSS: `k3s-server` 983 MiB, containerd 169 MiB, 14 shims 304 MiB,
  tailscaled 51 MiB. RSS counts shared pages once per process, so this
  overstates; the node reported 1,622 MiB available. The 2.6 GB ceiling in
  decision 3 was derived from the 1.1 GB figure and no longer has that
  margin — see [`architecture.md`](../architecture.md) §11.

