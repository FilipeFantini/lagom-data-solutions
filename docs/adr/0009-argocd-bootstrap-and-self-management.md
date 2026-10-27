# ADR-0009 — Argo CD: pinned Helm chart, app of apps, self-managed

- **Status:** Accepted — decision 4 (the deploy key) superseded by
  [ADR-0017](0017-public-repository-from-a-snapshot.md)
- **Date:** 2026-10-13

## Context and problem

M1 installs Argo CD, the component that turns this repository into the
cluster's source of truth. Four questions have to be answered once, because
every later component follows the same pattern:

1. How is an upstream component installed — raw manifests or a Helm chart?
2. How does Argo CD learn which applications exist?
3. Who manages Argo CD itself after the first install?
4. How does Argo CD read a private repository?

## Requirements and constraints

- Every workload declares resources
  ([`engineering-protocol.md`](../engineering-protocol.md) §16.5).
- Versions are pinned; an upgrade is a reviewed change, not a side effect.
- After bootstrap, nothing reaches the cluster except through `main`.
- The repository credential grants the least possible access.
- The operator must be able to read what is configured and why.

## Alternatives considered

**Raw upstream manifests (`install.yaml`) with Kustomize patches.** No extra
tool, and every object is visible. Rejected: the upstream file declares no
resources, so each of six components needs a patch to add them and to remove
Dex. Those patches are more code to maintain than a values file, and they
break silently when upstream renames a container.

**`core-install` (headless Argo CD, no UI or API server).** Lightest option.
Rejected because the operator is learning the reconciliation loop, and the UI is
where its state is visible. Its server costs ~50 MB.

**Personal access token or GitHub App for repository access.** A fine-grained
token can be scoped to one repository but belongs to a person and expires. A
GitHub App is the best option at scale but is more to set up than one repository
justifies.

## Decision

1. **Upstream Helm chart, pinned, with a values file in the repository.** Argo
   CD is chart `argo/argo-cd` 10.10.3 (Argo CD v3.5.5), configured by
   [`platform/infra/argocd/values.yaml`](../../platform/infra/argocd/values.yaml).
   The values file holds only what differs from the chart defaults. Later
   components with an upstream chart follow the same pattern.
2. **App of apps.** A `root` Application watches `platform/infra/apps/` and
   creates every Application it finds there, including itself. Adding a
   component means adding one file to that directory.
3. **Argo CD manages itself.** The `argocd` Application combines the pinned
   chart with the values file from this repository, so changing Argo CD is a
   commit like any other. Bootstrap is the only manual step: `helm install`
   once, then `kubectl apply` of the root Application.
4. **Repository access through a read-only deploy key.** It is an SSH key that
   GitHub binds to this repository alone, with read permission only. The
   private key exists only inside the cluster, in a Secret created at bootstrap
   and never committed — the credential Argo CD needs to read the repository
   cannot itself come from the repository.

Two settings within the decision:

- **Resources: memory request and limit, CPU request only.** CPU is
  compressible: a container over its CPU request runs slower, while one over its
  memory limit is killed. A CPU limit would only add throttling on a node whose
  scarce resource is memory. This refines §16.5 of the protocol, which is
  updated to say so.
- **Dex and notifications are disabled**, and the ApplicationSet controller runs
  at zero replicas: no single sign-on, no notification channel, and no
  generator is needed yet.

## Consequences

**Positive.** One pattern for every upstream component. Argo CD's own
configuration is reviewed and versioned like everything else. The repository
credential can do nothing but read this repository.

**Negative.**

- **Self-management can lock itself out.** A bad values change can break Argo
  CD, which then cannot apply the fix. Pruning is disabled on the `argocd`
  Application so that a mistake cannot delete Argo CD's own objects, and the
  runbook keeps the `helm upgrade` command as the break-glass path.
- **After the handover, Helm's release record goes stale.** Argo CD applies the
  rendered chart itself and does not update Helm's record of the release, so
  `helm list` shows the bootstrap revision forever. `helm` is used only for
  break-glass.
- **The deploy key lives only in the cluster.** Rebuilding the cluster means
  generating a new key and registering it again; the runbook has the steps.
- **The `default` AppProject is used**, which allows any source repository and
  any destination. One operator and one repository do not justify a narrower
  project yet; the trigger is a second team or repository.

## Risks, cost, and reversal

Measured at install, idle with no Applications: ~137 MiB across the four
running pods, against 480 MiB of declared requests. The requests are kept until
usage is measured with Applications under management, then set from the
numbers ([`architecture.md`](../architecture.md) §11).

Reversal is cheap in each part: the chart can be replaced by raw manifests, and
the deploy key by a GitHub App, without changing the app-of-apps layout.
