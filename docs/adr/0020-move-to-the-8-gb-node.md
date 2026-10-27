# ADR-0020 — Move to the 8 GB node (CAX21) for M3, pending Hetzner capacity

- **Status:** Accepted
- **Date:** 2026-10-27

## Context and problem

[ADR-0016](0016-ci-ceiling-2-2-gb.md) projected that M3 does not fit the
4 GB CAX11: with Dagster at the 600 MiB measured in
[ADR-0011](0011-memory-viability-on-4gb.md)'s spike, declared requests reach
about 2,630 MiB against a 2.2 GB ceiling (about −380 MiB, its 2026-10-19 note).
The roadmap's trigger for the 8 GB node is "a planned M3 or M5 component does
not fit under the 2.2 GB ceiling after tuning".

Tuning would have to remove about 380 MiB of declared requests. Nothing
identified so far comes close: memory limits on k3s's own components (an open
M1 item) bound what they may grow to, and are done for that reason, not to
make room for Dagster.

On 2026-10-27 the operator tried to resize the node to a CAX21 and Hetzner had
no capacity for it.

## Decision

**The platform moves to a Hetzner CAX21 (2 → 4 ARM vCPU, 4 → 8 GB RAM) before
Dagster enters (M3).** Decided by the operator on 2026-10-27, without waiting
for Dagster's own measurement, since the projected gap is too large for it to
close.

**How:** a resize in place, as ADR-0002 and ADR-0011 describe — one reboot,
disk and addresses kept. The operator retries while Hetzner has no capacity.

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
leaves room under the ceiling for the backup's resident cost
([ADR-0012](0012-cloudnative-pg.md): the Barman Cloud Plugin plus
cert-manager), which on 4 GB competed with Dagster.

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
