# ADR-0021 — Traefik and servicelb disabled; local-path and metrics-server managed by Argo CD

- **Status:** Accepted
- **Date:** 2026-10-27
- **Supersedes:** in part, [ADR-0002](0002-single-node-k3s-hetzner.md)'s "k3s
  defaults are kept" for Traefik, servicelb, local-path and metrics-server.
  CoreDNS and SQLite stay as ADR-0002 left them.

## Context and problem

k3s installs five packaged components outside Git: CoreDNS, Traefik with its
servicelb, local-path and metrics-server. The M1 roadmap item was to give them
memory limits "through `HelmChartConfig`". Inspection on 2026-10-27 found that
premise wrong, and found three more problems:

- **`HelmChartConfig` reaches Traefik only.** The others are k3s *addons*:
  plain manifests that k3s rewrites on every start, so an edit to them is
  reverted ([k3s docs, packaged components](https://docs.k3s.io/installation/packaged-components)).
- **Traefik serves nothing.** No Ingress or IngressRoute exists in the
  cluster. It still uses 120 MiB, and servicelb publishes it on ports 80 and
  443 of the node's public address. Only the Hetzner firewall keeps them
  closed.
- **The budget check under-counts.** It adds 170 MiB for these components,
  from M1 measurements of Traefik (~20 MiB) and local-path (~10 MiB). Today
  they use 120 and 47 MiB.
- **Two of them declare no limit**, against engineering-protocol §16.5.

## Decision

- **Traefik and servicelb are disabled** in the k3s configuration
  (`disable:` in `/etc/rancher/k3s/config.yaml`). Nothing uses them. When an
  ingress is needed, it enters by its own trigger. M4's Cloudflare Tunnel does
  not need one: `cloudflared` forwards to a Service.
- **local-path and metrics-server are disabled as addons and installed by
  Argo CD**, at the versions k3s ran (local-path-provisioner v0.0.37,
  metrics-server v0.9.0), with memory requests and limits:
  - local-path is a manifest vendored from upstream into
    [`platform/infra/local-path/`](../../platform/infra/local-path/). It keeps
    k3s's storage path and scripts, so existing volumes are served unchanged.
  - metrics-server is the upstream chart, with k3s's arguments.
- **CoreDNS stays a k3s addon.** It already declares a request and a limit, and
  replacing the cluster's DNS buys nothing.

The budget check's allowance for components outside Git drops to CoreDNS's
70 MiB request. The new Applications are counted by their own requests, like
every other workload.

## How the switch is made

k3s actively uninstalls a disabled addon: it deletes the objects in its
manifest. The PersistentVolumes local-path created are not among them: they
carry no k3s ownership. The Postgres volumes stay bound and their data stays
on disk. The order is therefore:

1. Merge nothing yet. Review the pull request and get it green.
2. Add the `disable:` list on the node and restart k3s. Running containers are
   not stopped (`KillMode=process`).
3. Merge. Argo CD installs local-path and metrics-server.

Between steps 2 and 3, for a few minutes, no volume can be provisioned or
deleted and `kubectl top` fails. Nothing on the platform creates a volume in
that window.

## Consequences

**Positive.** Every resident workload except CoreDNS is in Git, under the
budget check and the manifest policy check. About 120 MiB is freed. Ports 80
and 443 are no longer published, so the firewall is a second layer for them,
not the only one.

**Negative.**

- **Upgrades become ours.** A k3s upgrade no longer brings new versions of
  local-path and metrics-server. They are bumped in Git like any chart.
- **The vendored local-path manifest is a copy.** Its header names its upstream
  version and every change made to it. An upgrade is a re-vendor and a diff.
- **A rebuilt node has no storage class until Argo CD syncs.** Postgres's
  Clusters wait for it on a fresh install. The bootstrap runbook says so.

## Risks, cost, and reversal

No cost. The risk is the switch itself, mitigated by the order above and by
checking that the volumes stay bound before merging.

Reversal: remove the entries from `disable:`, restart k3s, and delete the two
Applications with prune off, then remove their objects by hand. k3s re-installs
its addons on start.

## Notes after acceptance

The text above is kept as accepted. These notes record what changed since,
without rewriting it.

- **2026-10-27 — the switch, as run.** k3s restarted at 16:44 UTC with the
  `disable:` list; it removed local-path's and metrics-server's objects, the
  StorageClass and the metrics APIService, and both PersistentVolumes stayed
  `Bound` with both Postgres Clusters healthy throughout. #16 was merged at
  16:45 and Argo CD had both Applications `Synced/Healthy` about 150 s later.
  **One step the order above did not foresee:** k3s uninstalls Traefik with
  `helm uninstall --wait`, and the Traefik Service, type LoadBalancer, kept
  the `service.kubernetes.io/load-balancer-cleanup` finalizer, which only
  servicelb removes — and servicelb was disabled in the same restart. The
  uninstall hung until the finalizer was removed by hand
  (`kubectl -n kube-system patch svc traefik --type=merge -p
  '{"metadata":{"finalizers":null}}'`); Traefik, its HelmCharts and CRDs were
  then gone. Disabling servicelb while a LoadBalancer Service exists needs
  that step.
