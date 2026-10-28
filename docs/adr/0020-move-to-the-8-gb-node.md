# ADR-0020 — Move to the 8 GB node (CAX21) for M3, pending Hetzner capacity

- **Status:** Accepted
- **Date:** 2026-10-27

## Context and problem

[ADR-0016](0016-ci-ceiling-2-2-gb.md) projected that M3 does not fit the
4 GB CAX11: with Dagster at the 600 MiB measured in
[ADR-0011](0011-memory-viability-on-4gb.md)'s spike, declared requests reach
about 2,630 MiB against a 2.2 GB ceiling (about −380 MiB, its 2026-10-19 note).
ADR-0011 (decision 4) and the roadmap's trigger table set the condition for
the 8 GB node: a planned component that does not fit under the ceiling after
tuning, observed rather than anticipated.

This ADR departs from "observed": the projection stands in for the
measurement, because ADR-0016 allowed that Dagster's real requests might come
in about 150 MiB under the spike, and the gap is now about 380 MiB. Tuning
would have to remove that much from declared requests. Nothing identified so
far comes close: memory limits on k3s's own components (an open
M1 item) bound what they may grow to, and are done for that reason, not to
make room for Dagster.

On 2026-10-27 the operator tried to resize the node to a CAX21 and Hetzner had
no capacity for it.

## Decision

**The platform moves to a Hetzner CAX21 (2 → 4 ARM vCPU, 4 → 8 GB RAM) before
Dagster enters (M3).** Decided by the operator on 2026-10-27, without waiting
for Dagster's own measurement, since the projected gap is too large for it to
close.

**How:** a resize in place — one reboot (ADR-0002, ADR-0011). By Hetzner's
own behaviour, not stated in those ADRs, the server keeps its addresses, and
its disk when the resize is CPU and RAM only. The operator retries while Hetzner has no capacity.

**If capacity does not return by the time M3 starts:** a new CAX21 where
Hetzner has capacity, built from Git. That rebuild is also the M2
disaster-recovery drill, and it brings in Terraform by its roadmap trigger.
Moving location changes the node's addresses; nothing depends on them from
outside (no inbound ports, Tailscale for administration).

**Until the move:** the 2.2 GB ceiling in [architecture.md](../architecture.md)
§11 stays, and nothing that needs more is merged. The new ceiling is set by
measuring the overhead on the CAX21, the way ADR-0016 set this one, not
derived by proportion.

## Consequences

**Positive.** M3 is planned against a node it fits on. The 8 GB node also
leaves room under the ceiling for the backup's resident cost — for instance
the Barman Cloud Plugin plus cert-manager, if that option is chosen
([ADR-0012](0012-cloudnative-pg.md)) — which on 4 GB competed with Dagster.

**Negative.**

- **Roughly double the node's monthly cost** (ADR-0011). The exact figure is
  the one Hetzner shows at resize time.
- **M3 is blocked on a vendor's capacity**, not on work. Work that does not
  need the larger node goes first.
- "Frugal, not capped" ([architecture.md](../architecture.md) §1) still holds:
  the larger node is room for the planned design, not licence to add to it.

## Risks, cost, and reversal

The risk is that capacity stays unavailable; the fallback above covers it.

Reversal: resize back to a CAX11, if the declared requests fit the 2.2 GB
ceiling again. A disk is never shrunk, so a resize that also grows the disk
cannot be reversed this way. Resize CPU and RAM only, which Hetzner offers as
an option, to keep the way back open.

## Notes after acceptance

The text above is kept as accepted. These notes record what changed since,
without rewriting it.

- **2026-10-28 — the node, obtained.** The resize stayed unavailable; the
  operator obtained an 8 GB server in another location, `lagom-shared-02`,
  the fallback above. The move to it is done by hand from the runbook and is
  the disaster-recovery drill ([ADR-0022](0022-platform-as-a-portfolio-of-architectures.md));
  Terraform waits for the next node.
- **2026-10-28 — moved.** Prod and staging run on `lagom-shared-02` since
  12:14 UTC, rebuilt from Git by the runbook in 20 min 31 s; measurements and
  gaps are in the runbook's *Disaster recovery*. The 2.2 GB ceiling still
  holds until the CAX21's overhead is measured.
