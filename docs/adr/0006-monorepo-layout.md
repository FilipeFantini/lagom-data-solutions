# ADR-0006 — Monorepo layout: platform, services, products

- **Status:** Accepted
- **Date:** 2026-10-12

## Context and problem

The platform is designed to grow by composition: more sources, more data
products, and eventually artifacts of kinds not yet present — a Power BI
project under version control, for instance, or a service with no SQL at all.

The initial layout grouped directories by technical artifact: `infra/`,
`ingestion/`, `dbt/`, `reports/`, `dashboard/`. That works while there is one
source. It degrades predictably: with five sources and three data products, a
change to one product touches five directories, and nothing in the tree says
which files belong together.

A layout must be chosen before the first code lands, because moving files later
is cheap but rewriting references, CI paths, and Argo CD paths is not.

## Requirements and constraints

- Adding a source or a product must not require reorganizing anything.
- A change to one workload should touch one directory.
- Must accommodate artifact types not yet planned, with the standing constraint
  that what is committed is reviewable as text.
- Argo CD watches paths, so the infrastructure boundary must be stable.
- No empty directories: a directory is created when it has content
  ([`../engineering-protocol.md`](../engineering-protocol.md) §2.2).
- dbt-core has no cross-project references, so the transformation layer cannot
  be split per service without losing `ref()`.

## Alternatives considered

**Group by technical artifact** (the initial sketch). Intuitive while small, and
it mirrors how tutorials present a stack. Rejected because it organizes by tool
rather than by what changes together: the blast radius of a change is spread
across the tree, and a reader cannot tell which pipeline a given config serves.

**One directory per service, fully self-contained**, each with its own dbt
project. The purest separation, and it is how application monorepos usually
work. Rejected because dbt-core cannot `ref()` across projects — cross-project
references are a dbt Cloud feature. Splitting would mean duplicating shared
dimensions or wiring sources by hand between projects, which trades a real
capability for tidiness.

**Separate repositories per service.** Maximum isolation, and a reasonable
destination if this ever becomes several teams. Rejected now: it multiplies CI
setup, makes an atomic change across layers impossible, and the platform has one
operator.

## Decision

Three top-level directories, divided by **blast radius and change frequency**
rather than by file type:

```
platform/            shared backbone — changes rarely, affects everything
  infra/             k8s manifests, Argo CD applications, Helm values
  orchestration/     Dagster deployment and shared resources
  warehouse/         the single dbt project
services/            workloads — change often, affect only themselves
  <service>/
    ingestion/       dlt pipeline or Redpanda Connect config
    assets/          Dagster assets for this service
    tests/           fixtures and tests
    README.md        what it is, its source, its freshness threshold
products/            what a consumer sees — changes often, affects one audience
  <product>/         Evidence site, Streamlit app, Power BI project
tools/               development and operational scripts
docs/                architecture, protocol, ADRs, runbook
```

**The test this layout must pass:** adding a source creates one directory under
`services/` and one directory of dbt models, and changes nothing else.

**dbt stays a single project** in `platform/warehouse/`, with
`models/staging/<service>/` mirroring the service name and `models/marts/<domain>/`
for the modelled layer. This is the one place a service is not fully
self-contained, and the naming convention is what keeps the two halves findable
from each other.

**Argo CD watches `platform/infra/` only.** Nothing outside that path can change
the cluster, which keeps the deployment boundary explicit and auditable.

**The requirement is form-agnostic, not Power BI specific.** `products/` must be
able to hold whatever a consumer sees, including artifact types nobody has
planned. The only standing constraint is that what lands there is **reviewable
as text**: a binary artifact defeats review and merge, so `.gitattributes`
marks known binaries as such.

Power BI is worth naming only as a worked example of that constraint, not as a
plan. It is *not* currently scoped. If it ever is, the constraint is already
satisfiable: the PBIP project format stores the semantic model as TMDL and the
report as PBIR, where each visual, page, and bookmark is an individually
versioned JSON file. Two caveats for whoever evaluates it: PBIR was still a
preview format requiring activation in Power BI Desktop as of late 2026, and
Fabric Git Integration exports the legacy single-file format unless the report
was imported as PBIR. A committed `.pbix` would not be acceptable either way.

Directories above are a **convention, not scaffolding.** Each is created by the
milestone that fills it; the convention is documented so that nothing has to be
reorganized when it is.

## Consequences

**Positive.** A new source or product is additive. The platform boundary is
stable, so Argo CD paths and CI triggers are written once. A reader can tell
from the path whether a file is shared infrastructure, one workload, or one
consumer's view. Per-directory CI filtering becomes possible later without
restructuring.

**Negative.** Three top-level directories is more ceremony than a flat tree
needs today, and the benefit only materializes at the third or fourth service.
The dbt exception means a service's transformation logic lives away from the rest
of the service — a real seam, mitigated only by naming discipline. Nothing in
the tooling enforces the convention, so it holds by review.

## Risks, cost, and reversal

Low risk and genuinely reversible: moving directories is a rename plus updating
Argo CD paths and CI globs. The cost rises with the number of references, which
is precisely why the decision is made before the first code rather than after.

If the project ever grows to multiple teams, the natural next step is splitting
`services/` into separate repositories — this layout is a step toward that, not
an obstacle.
