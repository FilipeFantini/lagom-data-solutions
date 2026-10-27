# ADR-0010 — Sealed Secrets for secrets in Git, key renewal off

- **Status:** Accepted
- **Date:** 2026-10-13

## Context and problem

Everything the cluster runs comes from Git ([ADR-0009](0009-argocd-bootstrap-and-self-management.md)),
and secrets must never be in Git in plain text. M2 brings the first real ones:
Postgres credentials per environment. `architecture.md` left the choice open
between Sealed Secrets and SOPS.

## Requirements and constraints

- A secret can be committed, reviewed, and deployed by Argo CD like any other
  manifest, without being readable from the repository.
- Minimal resident memory: RAM is the constraint this platform is designed
  against.
- No change to how Argo CD renders manifests.
- Losing a decryption key must not be a silent, permanent loss of every secret.

## Alternatives considered

**SOPS with age.** It encrypts values inside ordinary YAML, and the operator can
decrypt locally. It adds nothing resident in the cluster, but Argo CD cannot
read SOPS files natively: it needs a plugin (KSOPS or helm-secrets) in the
repo-server, which means a custom repo-server image or a sidecar, and the age
private key mounted into Argo CD. That is more moving parts in the component
everything else depends on.

**External secret store (Vault, 1Password Operator, External Secrets).**
Secrets stay out of Git entirely. Rejected on memory and scope: Vault alone
exceeds the controller below by an order of magnitude, and the 1Password
Operator ties the cluster to a paid external service.

## Decision

**Sealed Secrets**, chart `sealed-secrets` 2.20.0 (controller v0.40.0), in
`kube-system`, managed by Argo CD from
[`platform/infra/sealed-secrets/values.yaml`](../../platform/infra/sealed-secrets/values.yaml).

How it works: the controller generates a key pair. Anyone with `kubeseal` can
encrypt a Secret with the **public** key; the result is a `SealedSecret` that is
safe to commit. Only the controller holds the **private** key, and it turns each
`SealedSecret` into a normal Secret inside the cluster. A sealed secret is bound
to its name and namespace by default, so it cannot be copied into another
namespace to be read there.

**Key renewal is off** (`keyrenewperiod: "0"`). By default the controller adds a
new key every 30 days, and each new key must be backed up off the cluster —
a missed backup makes every secret sealed with that key unrecoverable after a
rebuild. With one operator, one deliberate rotation procedure is safer than a
recurring backup obligation.

**The private key is backed up to 1Password** by the operator, and restored
before anything else on a rebuild. The runbook has both commands.

## Consequences

**Positive.** Secrets are versioned and reviewed like everything else.
Argo CD needs no plugin: a `SealedSecret` is just another resource. The
controller is one small Go process.

**Negative.**

- **Secrets cannot be read from the repository**, not even by the operator. To
  check a value, read the Secret in the cluster. This is the point, and it is
  also friction.
- **The cluster's key is a single point of loss.** Without the backup, a rebuilt
  cluster cannot decrypt anything in Git, and every secret must be re-created
  and re-sealed.
- **No automatic key renewal.** The same key protects every secret until it is
  rotated by hand; a leaked key exposes everything sealed so far.

## Risks, cost, and reversal

Memory is measured at install and recorded in
[`architecture.md`](../architecture.md) §11.

Reversal: unseal in the cluster, re-encrypt with SOPS or move to an external
store, and remove the controller. The trigger would be a second cluster that
must share secrets, or a requirement to read secrets outside the cluster.
