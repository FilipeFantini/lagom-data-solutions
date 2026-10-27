# ADR-0002 — Single-node k3s on a Hetzner CAX11

- **Status:** Accepted
- **Date:** 2026-10-12

## Context and problem

The platform needs a Kubernetes environment that is real enough to teach GitOps
and platform engineering, cheap enough to defend as an SMB-grade solution, and
small enough that the scarcity is felt in data processing rather than in
overhead.

Two hardware options were available: an existing Raspberry Pi 3B with 1 GB of
RAM, and a small cloud VPS.

## Requirements and constraints

- Genuine Kubernetes, so that what is learned transfers to EKS, GKE, or kubeadm.
- Resident footprint low enough to leave meaningful room for data jobs.
- Monthly cost in the order of a few euros.
- A story that is credible for a small business, not a hobby setup.

## Alternatives considered

**Raspberry Pi 3B alone (1 GB).** k3s alone consumes around 300 MB — a third of
the budget — leaving roughly 300 MB for jobs after Flux, a collector, and a web
server. It also forced the lightest option at every layer, excluding Dagster.
Two further problems: the SD card is a worse bottleneck than the RAM (no USB3,
and constant writes kill cards in months), and no small business runs a
Raspberry Pi in production, so the setup reads as a hobby regardless of its
quality.

**Full kubeadm Kubernetes on the VPS.** Roughly 1.2 GB for the control plane
against k3s's 300 MB, for an identical API. The extra ~900 MB is a quarter of the
VPS, better spent on Dagster and dbt jobs. Nothing learned on k3s fails to
transfer.

**Talos Linux.** Extends the declarative model down to the operating system —
immutable, no shell, configured through `talosctl`. Rejected for now and
recorded separately, because the reasoning is about sequencing rather than
hardware: see the "Deferred" note below.

**Hetzner CX23 (Intel/AMD) instead of CAX11 (ARM).** Same specs, but the CAX
runs on Ampere Altra and benchmarks at more than double the Intel plan's
multithread score. ARM also matches the Pi, which is arm64. (The Intel plan in
this line was renamed from CX22 to CX23.)

## Decision

A **Hetzner CAX11** (2 ARM vCPU, 4 GB RAM, 40 GB SSD) running **k3s** as control
plane and main node. The **Raspberry Pi 3B joins as an agent node** for edge
collection, keeping the hybrid edge/cloud topology that is k3s's classic use
case.

k3s defaults are kept but understood as k3s choices rather than upstream
behaviour: Traefik for ingress, local-path for storage, SQLite as datastore.

**Talos is deferred to a second milestone.** The argument in its favour —
a fully declarative machine — is also the argument for deferring it: if the
platform is in Git and Argo CD reconciles, replacing the operating system
underneath is a rebuild and a reconfiguration, roughly an afternoon. That
migration is not a cost, it is proof, and it can only be demonstrated by having
done it. Against doing it now: ~1.1 GB of control plane (upstream Kubernetes
plus etcd) against ~300 MB, which is close to the whole Dagster budget; two hard
things at once, with no shell to debug in; a steeper onboarding for the second
developer; no ready Hetzner image; and etcd's sensitivity to fsync on shared
vCPU. A local throwaway Talos cluster (`talosctl cluster create`) is free and
removes the mystery in the meantime.

## Consequences

**Positive.** Roughly 1.8 GB resident for the eight-piece core, leaving about
2.2 GB for ephemeral jobs. Scarcity now bites where it teaches — data processing
— rather than on the control plane. Cost stays around EUR 5/month. The Pi keeps
a real role.

**Negative.** No high availability: a single node means maintenance takes
everything down. SQLite as datastore cannot do HA. local-path pins volumes to
the node, so horizontal scaling later needs either node affinity or a real CSI
driver such as Longhorn. ARM requires occasional attention to multi-arch images.

## Risks, cost, and reversal

Vertical scaling is trivial: Hetzner resizes the VM with one reboot. Horizontal
scaling needs the datastore moved to embedded etcd across three nodes and the
storage question answered. Moving to kubeadm or Talos means rebuilding the
cluster and repointing Argo CD, which is the intended reversal path and is
cheap precisely because everything is declarative.

**ARM compatibility was verified, not assumed.** The two pieces most likely to
lack arm64 both publish it: Dagster (`dagster/dagster-k8s`, amd64 + arm64 on
current tags) and PostgREST, which is Haskell. Everything else is either Go
(k3s, Argo CD, Traefik, NATS, Redpanda Connect, cloudflared, Tailscale, Sealed
Secrets), an official multi-arch image (Postgres), or Python with published
aarch64 wheels (dlt, dbt, DuckDB, Streamlit).

The residual ARM risk is **CI, not runtime**: GitHub Actions default runners are
amd64, so building an arm64 image there needs QEMU emulation (slow) or an ARM
runner. Most of the stack uses upstream images, so this likely affects only the
dlt and dbt job image. To be settled in M1.

**Availability risk, recorded October 2026.** CAX11 belongs to Hetzner's
Cost-Optimized line, which the vendor describes as deliberately built on older
hardware generations with a limited number of available servers. If CAX11 is
unavailable in the wanted region, the fallbacks are CAX21 (8 GB, more
expensive, still ARM) or the Regular Performance line — which is CPX on AMD,
meaning x86 and the loss of both the ARM match with the Pi and the
price-performance advantage.

**Pricing is unconfirmed.** Third-party trackers report a price increase in
April 2026 and disagree with each other on the current figure. Hetzner's own
plan pages render prices through client-side web components that did not
hydrate when checked, so no figure from them is quoted here. **Confirm in the
Hetzner Console before provisioning**, and record the real figure in this ADR
at that point.

## Notes after acceptance

- **2026-10-12 — k3s measured.** On the provisioned node, idle, the
  `k3s-server` process holds 627 MB and the container runtime another
  ~265 MB, against the ~300 MB this ADR quoted. The "~1.8 GB core / ~2.2 GB for
  jobs" figures above are superseded by the measured budget in
  [`architecture.md`](../architecture.md) §11. The comparison with kubeadm and
  Talos (~1.1–1.2 GB) used estimates of the same kind, unmeasured here, so the
  advantage of k3s is likely smaller than stated; the decision is unchanged.
- **2026-10-12 — price confirmed.** CAX11 was available in `nbg1` and the
  Hetzner Console showed **EUR 7.37/month**. Whether that figure includes VAT
  and the primary IPv4 was not recorded. "Around EUR 5/month" above is
  superseded by it.
