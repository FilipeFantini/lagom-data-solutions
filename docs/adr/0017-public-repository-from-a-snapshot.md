# ADR-0017 — Publish as a new public repository from a single-commit snapshot

- **Status:** Accepted — supersedes decision 4 of
  [ADR-0009](0009-argocd-bootstrap-and-self-management.md)
- **Date:** 2026-10-27

## Context and problem

The repository was created private, meant to become public once the operator
decided to publish it ([`roadmap.md`](../roadmap.md#m0--accounts-and-provisioning)).
Before publishing, a review scanned the working tree, every commit on every
branch, GitHub's pull-request refs, pull-request text, and the Actions logs.
It found no secret. It did find identifiers of the operator and the network
that a public repository would expose for good:

- the operator's personal e-mail, as the author of most commits and in the
  Tailscale ACL of the runbook;
- the tailnet's DNS name and the node's tailnet address;
- the node's public IPv4, in the text of two pull requests;
- the operator's SSH public key and the node's login user, in the runbook.

None of these grants access on its own; the controls do not depend on them
being secret. The operator chose to expose as little as possible anyway.

The question is how to publish without them. Editing the files today does not
help, because history keeps every earlier version. Rewriting history does not
reach GitHub's `refs/pull/*`, which are read-only and keep every commit ever
pushed to a pull request.

## Requirements and constraints

- Nothing in the public repository identifies the operator beyond the GitHub
  account that owns it and the copyright holder in `LICENSE`.
- No secret is published; sealed ciphertext is safe by design
  ([ADR-0010](0010-sealed-secrets.md)).
- The cluster keeps running through the change; at worst Argo CD pauses.
- The repository stays the source of truth, including for what happened before
  publication.
- No monetary cost.

## Alternatives considered

**Flip the existing repository to public.** One click. Rejected: every item
above becomes permanent public history.

**Rewrite history, then flip.** `git filter-repo` replaces the e-mail and the
values in every commit, every branch is force-pushed, and GitHub Support is
asked to purge the pull-request refs and cached views. Rejected: it depends on
Support, pull-request pages keep pointing at commits that no longer exist, and
image tags (commit SHAs, [ADR-0015](0015-images-on-ghcr.md)) stop matching
any commit — the same losses as a fresh start, with more steps.

**A separate pseudonymous GitHub account or organization.** The only option
that removes the operator's name as well. Rejected by the operator: the GitHub
account is the project's public identity, as for any open-source author.

## Decision

1. **The private repository is kept as an archive.** It is renamed
   `lagom-data-solutions-archive`, stays private, and is archived (read-only).
   It holds the full history: every commit, pull-request discussion, and
   reviewer report before publication.
2. **A new public repository takes the original name.** Its history starts
   with one commit: the archive's `main` at publication, plus this change.
   Commits use the account's GitHub `noreply` address, never a personal one.
3. **Identifiers leave the tree.** The runbook writes them as placeholders and
   says where each value is found
   ([`architecture.md`](../architecture.md#13-runbook)). Kept on purpose: the
   GitHub account name (repository URL, image paths, the OCI source label), the
   license holder, the node's hostname, the Hetzner plan, location, and price,
   and the domain. Each is public elsewhere or is the reasoning the project
   documents.
4. **Argo CD reads the repository anonymously over HTTPS.** Every Application
   names `https://github.com/FilipeFantini/lagom-data-solutions.git`. The
   deploy key and the cluster Secret that held its private half are deleted.
   This supersedes decision 4 of ADR-0009: a public repository needs no
   credential to be read, and a credential that does not exist cannot leak.
5. **The node's public IPv4 is replaced.** The old address only ever appeared
   in the archive's pull-request text, which stays private; replacing it is
   defence in depth.
6. **`main` gets branch protection.** The exception in
   [CONTRIBUTING](../../CONTRIBUTING.md#branch-protection) was to be revisited
   when the repository became public, because protection is free on public
   repositories.

### Cutover order

The order is what keeps the cluster safe. Argo CD only changes the cluster
from a revision it could read, so a failed read pauses reconciliation and
changes nothing.

1. Open pull requests are merged in the private repository, so the snapshot is
   a complete `main`.
2. The private repository is renamed. GitHub redirects the old name to the new
   one, so Argo CD keeps syncing over SSH meanwhile.
3. The public repository is created under the old name and the snapshot is
   pushed. From here the old SSH URL resolves to the public repository, where
   the deploy key is not registered: Argo CD reports a comparison error and
   leaves the cluster as it is.
4. The operator applies `platform/infra/apps/root.yaml` from the new checkout —
   the same single manual command as the bootstrap hand-over. `root` now reads
   over HTTPS and renders every child Application with the HTTPS URL.
5. Verify: every Application `Synced` and `Healthy` at the new commit.
6. Delete the repository Secret in `argocd` and the deploy key on the archive;
   archive the archive.
7. Grant the public repository write access to the two GHCR packages
   (*Package settings → Manage Actions access*). The packages stay linked to
   the archive; without the grant the first publish fails with a 403.
8. Enable branch protection on `main`.
9. Replace the node's public IPv4 in the Hetzner Console. A Primary IP can
   only be swapped with the server powered off: create a new IPv4, assign it,
   power on, delete the old one. Then re-run the closed-port probe in the
   runbook against the new address, and check that no DNS record names the
   old one. Tailscale finds the new endpoint on its own; the `tls-san` names
   do not include the public address, so k3s needs no change.

## Consequences

**Positive.**

- No repository credential in the cluster, and nothing to re-register when
  the cluster is rebuilt.
- Branch protection becomes available at no cost, which ends the accepted debt
  in [ADR-0013](0013-agent-driven-development-guardrails.md) once enabled.
- The repository can be read by anyone, which is the portfolio goal in the
  roadmap.

**Negative.**

- **Public history starts at the snapshot.** Earlier commits, pull requests,
  and reviewer reports are only in the private archive. A reference to them
  from the public repository cannot be followed by a reader.
- **Images built before publication** carry tags naming commits that exist
  only in the archive. Traceability from image to public commit resumes with
  the first build in the public repository.
- **The promotion check trusts the snapshot as its baseline.** Which digest
  staging pinned first, before publication, is no longer in the history it
  reads. On the first push there is no previous tip at all, so the CI job uses
  the pushed commit as the base; prod must still pin only digests staging pins
  in it.
- **Anonymous reads are subject to GitHub's limits for unauthenticated
  clients.** Argo CD polls every few minutes, far below them.
- **The packages stay private**, so the two pull secrets stay. ADR-0015
  rejected public packages *while the repository is private*; that condition is
  gone, and the question is open for its own decision.
- **The design is public**, including the security controls. They were built
  to hold when known: the ACL, the closed firewall, and sealed secrets do not
  rely on anyone not knowing they exist.

## Risks, cost, and reversal

No monetary cost.

The main risk is in the cutover: between steps 3 and 5 Argo CD reconciles
nothing. Workloads keep running and the CronJobs keep firing; only a change
merged in that window waits.

Publication cannot be reversed in practice: the repository can be made private
again, but what was public may already be cloned or indexed. Anonymous HTTPS
can be reversed by registering a deploy key again, with the procedure that
ADR-0009 describes.
