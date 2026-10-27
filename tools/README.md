# tools/

Development and operational scripts: the CI checks on manifests, local
environment helpers, one-off maintenance commands.

A script here is held to the same standard as the rest of the repository — it is
read and run by someone who did not write it. That means arguments over edited
constants, a clear failure when a precondition is missing, and no destructive
action without an explicit flag.

| Script | What it does | Run |
|---|---|---|
| [`resource_budget.py`](resource_budget.py) | Renders every Argo CD Application and fails on missing resources or a total over the ceiling — [architecture.md §11](../docs/architecture.md#11-resource-budget) | `uv run --project tools python tools/resource_budget.py` |
| [`promotion_check.py`](promotion_check.py) | Fails if prod pins an image without a digest, or a digest staging had not pinned on `main` first — [ADR-0015](../docs/adr/0015-images-on-ghcr.md) | `uv run --project tools python tools/promotion_check.py --base origin/main` |
| [`manifest_policy.py`](manifest_policy.py) | Fails an Application that leaves `prune` implicit, a chart not pinned to an exact version, a Git source outside this repository, or a rendered image without a tag or digest — [engineering-protocol §18](../docs/engineering-protocol.md#18-agent-driven-development) | `uv run --project tools python tools/manifest_policy.py` |

`tools/` is a small `uv` project: `pyproject.toml` declares dependencies and the
ruff, mypy, and pytest settings, and `uv.lock` pins them. CI runs
`ruff format --check`, `ruff check`, `mypy --strict`, and `pytest` on it.

## Manifest policy check

[`manifest_policy.py`](manifest_policy.py) reads every Application in
`platform/infra/apps/`, renders it the way Argo CD does (it imports
`resource_budget.py`'s rendering, so it needs `helm` and network access to the
chart repositories), and enforces four rules:

1. `spec.syncPolicy.automated.prune` is set to `true` or `false`. A missing key
   fails, including an Application with no `automated` block: the default is
   what the rule forbids relying on.
2. Every Helm source's `targetRevision` is an exact version — digits and dots,
   with an optional prerelease or build suffix. Ranges, wildcards, `latest`,
   a leading `v`, and an empty value fail.
3. Every source without `chart:` points at this repository. `main` is correct
   there by design (Argo CD watching `main` is the GitOps loop); any other
   repository fails until a pinning rule for it exists.
4. Every container and init container image in the rendered manifests, and a
   CloudNativePG `Cluster`'s `spec.imageName`, has a tag or a digest, and the
   tag is not `latest`. Images under `ghcr.io/filipefantini/` must carry a
   digest, as [ADR-0015](../docs/adr/0015-images-on-ghcr.md) requires.

An Application that breaks rule 2 or 3 is reported but not rendered, so its
images go unchecked until it is fixed; the report names it.

**What it does not check** (engineering-protocol §18 rule 5), so a green result
is not read as more than it proves:

- That a pinned chart version or digest exists, or is the one that was tested.
  [`promotion_check.py`](promotion_check.py) covers the staging-then-prod order
  for digests; nothing checks that a tag still points at the same bytes.
- Third-party images pinned by a tag only (`nginx:1.30.5-alpine`): a tag can be
  moved. Only this repository's own images are held to a digest.
- Images created outside the rendered manifests: Pods an operator creates at
  runtime beyond a `Cluster`'s `imageName`, other image fields in custom
  resources, images named only in `args` or environment variables, and what
  k3s installs outside Git.
- Any other Application field (`selfHeal`, `project`, `syncOptions`,
  `destination`), or whether the prune value is the right one: only that it is
  stated.
- Kinds other than `Application` in `platform/infra/apps/`, and Applications
  defined elsewhere.
- Anything `helm template` cannot see without a cluster (`lookup`, the
  cluster's API versions).
