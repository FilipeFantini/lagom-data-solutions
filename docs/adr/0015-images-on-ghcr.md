# ADR-0015 — Images built in CI, published privately to GHCR, promoted by digest

- **Status:** Accepted
- **Date:** 2026-10-16

## Context and problem

The USGS pipeline (`services/usgs/`) has to run in the cluster as a job. A job
runs a container image: the code, Python, and its locked dependencies, packed
together. Three questions follow. Where is the image built? Where is it stored,
so the node can pull it? And how does a change reach staging before prod, when
Argo CD applies `main` to both?

The constraints are cost and attention. The operator will not pay for GitHub
plans or Actions, the repository is private, and the node has no inbound port.

## Requirements and constraints

- No monetary cost. Verified on 2026-10-16 in GitHub's billing documentation:
  - Container registry (`ghcr.io`) storage and bandwidth are "currently free",
    with at least one month's notice before that changes.
  - A Free account includes 2,000 Actions minutes a month for private
    repositories, and standard arm64 Linux runners draw on them.
  - Without a payment method on file, usage beyond the quota is blocked, not
    billed.
- The image runs on the node's architecture, arm64.
- What runs is an immutable artifact, traceable to a commit
  ([ADR-0009](0009-argocd-bootstrap-and-self-management.md): versions are
  pinned, and upgrades are reviewed changes).
- A change reaches staging before prod
  ([ADR-0007](0007-three-environments.md)), and staging's credentials open
  nothing in prod.
- The code is private, so the image is private too.

## Alternatives considered

**No image of our own.** The job starts from the official `uv` image, clones the
repository, and installs the locked dependencies on every run. There is no
registry and no build. Rejected as the default: every run depends on PyPI and
GitHub being reachable, starts slower, and needs a repository credential in the
cluster. Above all, what runs is assembled at run time rather than built and
tested once. It is the exit plan if GHCR stops being free, because it needs no
code change.

**A registry inside the cluster, with in-cluster builds (kaniko).** Nothing
leaves the node. Rejected: two more components, build memory spikes on a node
whose margin is ~1 GB, and more to operate than the problem warrants.

**A public package on GHCR.** No pull credential needed. Rejected while the
repository is private, because the image contains the code.

## Decision

1. **Build in CI.** On a push to `main` that changes `services/<name>/`, a
   workflow builds `ghcr.io/filipefantini/lagom-<name>`, tagged with the commit
   SHA, natively on a standard `ubuntu-24.04-arm` runner. The base image is
   pinned by digest, and dependencies come from `uv.lock` (`uv sync --locked
   --no-dev`). Only that job holds `packages: write`, through the workflow's
   own `GITHUB_TOKEN`; no personal token is used to publish.
2. **Reference by digest.** Manifests name images as `name:tag@sha256:…`, as
   the Postgres image already is. The tag is for readers; the digest is what is
   pulled.
3. **Promotion is a commit.** Staging and prod each pin their own digest. A code
   change takes three pull requests: the code itself, whose merge to `main`
   builds the image; one that sets staging's digest to it; and one that copies
   the same digest into prod. All are merged by the operator today
   ([ADR-0013](0013-agent-driven-development-guardrails.md)). That prod only
   receives digests staging ran is a convention until a CI check asserts it
   (roadmap Track G).
   This answers how a change reaches staging first while Argo CD watches only
   `main`: the environments differ in *which digest* they pin, not in which
   branch they follow.
4. **Jobs run as CronJobs applied by Argo CD.** Each environment's pipeline is
   a CronJob in its namespace, pinned to that environment's digest and synced
   from `main` like everything else. A run outside the schedule is
   `kubectl create job --from=cronjob/<name>`. This replaces ADR-0007's "Jobs
   triggered by CI": CI is not on the tailnet and the node has no inbound
   port, so CI never reaches the cluster.
5. **Pull credentials per environment.** The package is private, so each
   namespace that pulls holds a sealed `dockerconfigjson` Secret
   ([ADR-0010](0010-sealed-secrets.md)) built from its **own** classic personal
   access token with only `read:packages`. GHCR accepts only classic tokens for
   this. The scope is account-wide: either token can pull every private package
   the account owns, so separate tokens buy independent revocation, not
   separate access. That is accepted while the account owns nothing else
   sensitive. A dedicated machine account is the fix if that changes. Tokens
   expire after one year, and rotation is a runbook step.

## Consequences

**Positive.**

- What runs in prod is byte-for-byte what was built and tested, traceable to a
  commit and a digest.
- Staging-before-prod is real without a second branch or a second Argo CD
  instance.
- Zero cost under today's GitHub terms, and no new component in the cluster.

**Negative.**

- **Promotion is manual:** three pull requests per change, two of them digest
  bumps.
  Automating the staging bump (a bot commit after the build) is deferred until
  the manual bumps become routine.
- **A dependency on GitHub** for building and serving images. If GitHub is down,
  nothing new deploys; running jobs keep the image the node already pulled.
- **Two tokens to rotate yearly**, created by the operator in GitHub's settings.

## Risks, cost, and reversal

**Trigger to revisit: GitHub announces billing for Container registry storage
or bandwidth.** The exit is the "no image" alternative above, which changes
only the job manifests. A second trigger is Actions minutes approaching the
monthly allowance. Today a pull request uses about 1 minute, and a build is
expected to add a few.

Reversal of the promotion model, if two pull requests per change become a
burden: staging follows the newest digest automatically and only prod is pinned
by hand.

## Notes after acceptance

The text above is kept as accepted. These notes record what changed since,
without rewriting it.

- **2026-10-19 — the promotion order is a CI check.** Decision 3 called it a
  convention until a check asserted it. `tools/promotion_check.py` now fails
  a change whose prod manifests pin an image by tag only, or by a digest that
  staging's manifests had not pinned in any commit before the change's base.
  It asserts "pinned on `main` first", not "ran successfully": CI never
  reaches the cluster (decision 4).
