# Roadmap

Execution order and entry triggers. Read before adding a component — several are
deliberately absent.

**Execution rule:** walking skeleton before any data source. Make the whole loop
work with the minimum, then thicken each piece.

**Two tiers** ([ADR-0023](adr/0023-sme-stack-duckdb-on-ducklake.md), proposed): the **SME stack** — DuckDB on DuckLake, Postgres
as its catalog, data on R2 — and, later, a big-data stack for comparison.
**The platform is a portfolio of data architectures** ([ADR-0022](adr/0022-platform-as-a-portfolio-of-architectures.md)): each
*showcase* is one architecture end to end on the shared backbone, published as
static pages and dashboards on getlagom.app. A component enters because a
showcase needs it.

**Principle 7 — defer with a trigger.** The full design in
[`architecture.md`](architecture.md) is the destination, not the starting point.
The core of M1–M3 is eight pieces: k3s, Argo CD, Tailscale, Sealed Secrets, dlt,
dbt, Postgres, Dagster.

## Trigger table

| Piece | Enters when |
|---|---|
| `staging` namespace | M2 — once there is something to promote |
| Postgres backup | Postgres holds state no source can rebuild (Dagster's metastore in M3, a non-replayable source in M6), or someone other than the operator relies on the database itself — the site does not: it serves pages built after each run — [ADR-0019](adr/0019-postgres-backup-deferred.md); accepted as debt, [architecture.md §12](architecture.md#12-accepted-risks) |
| Object storage (Cloudflare R2) | the SME-stack spike (M3), as the store of DuckLake's data files ([ADR-0023](adr/0023-sme-stack-duckdb-on-ducklake.md), proposed) |
| DuckDB and DuckLake (the SME stack) | the spike in M3; the warehouse moves from Postgres when it passes ([ADR-0023](adr/0023-sme-stack-duckdb-on-ducklake.md), proposed; until then [ADR-0008](adr/0008-postgres-for-all-layers.md)) |
| Second VPS (real environment isolation) | a real client |
| Terraform for resources outside the cluster (Hetzner server and firewall, Tailscale ACL, Cloudflare DNS, R2 and Pages) | the next node created or rebuilt. **Deferred by the operator on 2026-10-28**, after the move to `lagom-shared-02` had been planned as its entry: it adds work outside the data showcases, and the candidate state backend, HCP Terraform's free plan, is one more freemium vendor. The CLI is free; the state backend is the choice that needs its ADR. Existing resources are adopted with `import`, which records them without recreating them, so `lagom-shared-02` can still be brought under code later ([ADR-0022](adr/0022-platform-as-a-portfolio-of-architectures.md)) |
| Evidence | M4 — the dashboard gallery on getlagom.app ([ADR-0022](adr/0022-platform-as-a-portfolio-of-architectures.md)) |
| Cloudflare Access (login) | the first content that must not be public. The site and its showcases are public data |
| NATS | second consumer of the same stream, or a replay requirement |
| Streamlit | an interactive app a static page cannot serve |
| Infrastructure observability (metrics and logs), shown on getlagom.app | the USGS showcase is live on getlagom.app (M4): the platform delivers data first, then shows how it runs. Candidate stack, chosen for resident memory and confirmed by its own ADR when it enters: VictoriaMetrics single-node (scrapes and stores, PromQL-compatible), node-exporter and kube-state-metrics as sources, VictoriaLogs for logs; Grafana only for the operator, over the tailnet. The site gets static snapshots exported after each run, like every showcase, never a live dashboard reaching the cluster ([ADR-0022](adr/0022-platform-as-a-portfolio-of-architectures.md)). Expected, not yet measured: lower resident memory than Prometheus and a simpler log store than Loki; the ADR measures the candidate before accepting it |
| PgBouncer (CloudNativePG `Pooler`) | first external BI consumer |
| Row Level Security | second consumer with segregated data |
| PostgREST | first API requirement |
| Metabase, Superset or Lightdash | a client needs ad-hoc, self-service exploration — behind login |
| 8 GB node | **decided 2026-10-27** for M3 ([ADR-0020](adr/0020-move-to-the-8-gb-node.md)); obtained 2026-10-28 as a new node in another location, `lagom-shared-02`, and the platform moved to it the same day |
| Big-data stack (Apache Iceberg, Spark or Trino, Airflow) | later, as the comparison that shows where the SME stack stops; infrastructure sized for it and its own ADR ([ADR-0023](adr/0023-sme-stack-duckdb-on-ducklake.md), proposed) |
| In-cluster policy engine (Kyverno, Gatekeeper) | a second writer to the cluster besides Argo CD — [ADR-0013](adr/0013-agent-driven-development-guardrails.md) |
| Automated staging digest bump (bot commit after a build) | manual staging bumps become routine, and the bot meets [ADR-0013](adr/0013-agent-driven-development-guardrails.md) rule 3 for infrastructure manifests — [ADR-0015](adr/0015-images-on-ghcr.md) |
| Run jobs without an own image (official `uv` image, clone at run time) | GitHub announces billing for Container registry storage or bandwidth — [ADR-0015](adr/0015-images-on-ghcr.md) |
| Agent merge for a class of change | the criteria in [ADR-0013](adr/0013-agent-driven-development-guardrails.md) rule 3 — deterministic gates required by branch protection, and a run of merges with no escape |

Re-introducing a practice excluded in
[`engineering-protocol.md`](engineering-protocol.md) §17 requires an ADR.

## M0 — Accounts and provisioning

- [x] Confirm pricing and CAX11 availability in the Hetzner Console, and record
      the real figure in [ADR-0002](adr/0002-single-node-k3s-hetzner.md) —
      available in `nbg1`, EUR 7.37/month as shown in the Console
- [x] Create the VPS with the settings below — `lagom-shared-01`, `nbg1`;
      steps and verification in the
      [runbook](architecture.md#provision-the-node-m0)
- [x] Point the domain at Cloudflare — `getlagom.app`, registered with
      Cloudflare Registrar, so registrar and DNS are the same account and there
      was nothing to repoint
- [x] Create the GitHub repository — private at first. It is meant to become
      public as a portfolio, where readable infrastructure is worth more than a
      CV bullet; going public is a deliberate step taken by the operator, since
      published history cannot be withdrawn
- [x] Publish it — as a new public repository whose history starts at a
      snapshot; the private history is kept in an archive
      ([ADR-0017](adr/0017-public-repository-from-a-snapshot.md))

### Provisioning settings

| Field | Value | Why |
|---|---|---|
| Location | `nbg1` (Nuremberg) for `lagom-shared-01`; `fsn1` (Falkenstein) for `lagom-shared-02` | EU, Cost-Optimized line available; the CAX21 was not available as a resize in `nbg1` ([ADR-0020](adr/0020-move-to-the-8-gb-node.md)) |
| Image | **Debian 13** | no snapd, less aggressive auto-upgrade; ~150 MB lighter resident than Ubuntu, which is ~6% of the job budget |
| Type | CAX11 (2 ARM vCPU, 4 GB) for `lagom-shared-01`; CAX21 (4 ARM vCPU, 8 GB) since `lagom-shared-02` | [ADR-0002](adr/0002-single-node-k3s-hetzner.md), [ADR-0020](adr/0020-move-to-the-8-gb-node.md). ARM, because the images are built for arm64 only |
| IPv4 | yes | IPv6-only breaks registries and endpoints that still lack v6 |
| IPv6 | yes | free |
| Private network | no | only links Hetzner servers; the Pi joins over Tailscale |
| SSH key | existing ed25519 (1Password) | password auth never enabled; root gets the key but cannot use it |
| Cloud config | [runbook](architecture.md#provision-the-node-m0) | creates a personal sudo user, disables root and password login |
| Volume | no | 40 GB local is enough for megabytes in Postgres; disk pressure is a lakehouse trigger ([ADR-0008](adr/0008-postgres-for-all-layers.md)) |
| Firewall | yes — inbound port 22 from the operator's IP only, until Tailscale is verified; then **no inbound rules** | runs outside the VM, so no RAM cost. **Never expose 6443.** Tailscale and Cloudflare Tunnel are outbound, so inbound drops to zero ([runbook](architecture.md#tailscale-acl-and-zero-inbound-ports-m1)) |
| Backups | no | VM rollback is not needed: the machine is reproducible from Git. Postgres today holds only data a re-load from the source rebuilds; its backup enters by its own trigger ([ADR-0019](adr/0019-postgres-backup-deferred.md)) |
| Placement group | no | only spreads multiple servers across physical hosts |
| Labels | `project=lagom`, `env=shared`, `role=k3s-server` | free, and saves effort in the CLI and the invoice |
| Name | `lagom-shared-01`, then `lagom-shared-02` | `<project>-<environment>-<index>`. The node hosts both the prod and the staging namespace ([ADR-0007](adr/0007-three-environments.md)), so it is `shared`; `lagom-prod-01` is left for a dedicated prod node |

**Cloud-init hardens SSH only — it does not install k3s.** Installing the
cluster from user-data would hide the mechanism this milestone exists to teach.
No swap, deliberately: on this node swap turns an OOM into undiagnosable
slowness.

Half an hour. The only code is the cloud-config, kept in the runbook.

## M1 — The empty GitOps loop

VPS with k3s, Tailscale, Argo CD, and a trivial `nginx` deployed **only via
commit**. No data yet.

Goal: prove that changing a YAML file on GitHub makes the cluster converge on
its own.

- [x] k3s on the VPS — `v1.36.5+k3s1`, see the
      [runbook](architecture.md#install-k3s-m1)
- [x] Tailscale on the node and the operator's machine, `kubectl` over the
      tailnet
- [x] Tailscale ACL: the node is `tag:lagom-node`; operators reach only SSH
      and the API, and the node reaches no one
- [x] Public port 22 closed — zero inbound ports on IPv4 and IPv6; break-glass
      in the [runbook](architecture.md#tailscale-acl-and-zero-inbound-ports-m1)
- [x] Decide whether the 2.6 GB request ceiling stands — it does; memory
      viability measured in a spike, with the 8 GB fallback criteria —
      [ADR-0011](adr/0011-memory-viability-on-4gb.md)
- [x] Confirm `k3s-server` stays bounded over 24 h with `GOMEMLIMIT` — 761 MiB
      RSS after 67 h on 2026-10-16, against 1,235 MB after 17 h without it
- [x] Argo CD (no Dex) watching `platform/infra/` —
      [ADR-0009](adr/0009-argocd-bootstrap-and-self-management.md)
- [x] Sealed Secrets configured — [ADR-0010](adr/0010-sealed-secrets.md):
      installed, a sealed secret decrypted in the cluster, the same file refused
      in another namespace, and the sealing key backed up to 1Password
- [x] nginx deployed via commit — a merged change reached the page in ~1.5
      minutes with no manual command; see the runbook's Deploy section
- [x] Resource budget check in CI — `tools/resource_budget.py`, see
      [architecture.md](architecture.md#11-resource-budget) §11
- [x] Memory limits on k3s's own components — not through `HelmChartConfig`,
      which reaches Traefik only: Traefik and servicelb disabled (nothing used
      them), local-path and metrics-server moved to Argo CD with requests and
      limits, CoreDNS kept (it declares both)
      ([ADR-0021](adr/0021-k3s-packaged-components-under-git.md))
- [x] PR workflow active from the first commit (only `main` is watched by Argo
      CD) — enforced by the ruleset on `main` since 2026-10-27; see
      [CONTRIBUTING](../CONTRIBUTING.md#branch-protection)
- [x] Runbook: bootstrap and deploy sections

## M2 — One dataset end to end

A single source, the simplest available: **USGS** (United States Geological
Survey) earthquake feed — public GeoJSON, refreshed every few minutes, no API
key, no practical rate limit, ready-made windows (past hour, past day, past 30
days). Each event carries magnitude, depth, coordinates, timestamp, and place.

It is the right source for this milestone because there is no authentication to
debug, the schema is stable, and the volume is small — the focus stays on the
conveyor, not the source.

Full path: **dlt** -> Postgres bronze -> `dbt run` -> silver and gold in the
same Postgres. Still no Dagster, only a CronJob. No object storage — see
[ADR-0008](adr/0008-postgres-for-all-layers.md).

Done when: a `SELECT` on gold returns rows, and reconciliation between layers
passes.

- [x] dlt pipeline for USGS (`rest_api` source, incremental) — first real
      load 2026-10-17: 10,168 events (30 days) into `lagom_dev` in 15 s
- [x] Verify whether dlt source config can live in separate YAML — it can: the
      whole `rest_api` block is in `services/usgs/ingestion/source.yaml`. One
      thing cannot be written in YAML, a Python callable (here `convert`, which
      turns the cursor into the ISO date the API wants); the entry point adds
      it. [ADR-0003](adr/0003-ingestion-split-dlt-benthos.md) is history and is
      not edited
- [x] CloudNativePG operator, memory measured — 31 MiB reconciling one
      Cluster; [ADR-0012](adr/0012-cloudnative-pg.md)
- [x] Postgres `Cluster` for prod (no PgBouncer yet); budget check counts the
      `Cluster`'s resources, since its Pods are not in Git — PostgreSQL 18.6,
      47 MiB idle; runbook section in [architecture.md](architecture.md#postgres-m2)
- [x] Bronze in Postgres via dlt; set `max_table_nesting` against the real
      payload — on the real USGS payload a column hint on
      `geometry__coordinates` (`data_type: json`) does the job without
      `max_table_nesting`: it keeps the one list as JSON and leaves any future
      list visible as a child table. On Postgres: `jsonb` coordinates,
      `double precision` magnitude; re-loading a loaded day left the 10,168
      rows unchanged (merge idempotent)
- [x] dbt project (`dbt-postgres`) with bronze/silver/gold — `dbt build` on
      real data: PASS=32 (3 models, 22 data tests, 7 unit tests)
- [x] Measure Postgres memory under `dbt run` against its 300 MB budget —
      peak 87 MiB in staging during `dbt build` at 10k rows
- [x] CronJob running dlt and dbt — staging verified 2026-10-18 (9,929 events,
      dbt PASS=32, 37 s); prod promoted with the same digests
- [x] Read-only roles in Postgres (RLS comes later) — group role
      `gold_reader` in both Clusters, granted by dbt on every build and
      asserted by a data test; staging verified 2026-10-27 (dbt PASS=34,
      `gold_reader_privileges` included), prod promoted with the same digest.
      No consumer login role exists yet
- [x] Reconciliation tests between layers — bronze → silver → gold → daily
      aggregate, as dbt singular tests
- [x] `staging` namespace with its own Postgres, ResourceQuota, LimitRange,
      NetworkPolicy denying staging to prod, and separate secrets. The
      operator's cluster-wide RBAC was revisited and kept — see the note in
      [ADR-0012](adr/0012-cloudnative-pg.md). Isolation verified 2026-10-17
- [x] Dev database `lagom_dev` in staging's Postgres, reached by port-forward —
      replaces the local dev environment
      ([ADR-0014](adr/0014-develop-against-staging.md)); `pg_hba` reject verified
- [x] **Decide the CI ceiling** now that the overhead is ~1.5 GB, not ~1.1 GB —
      lowered to 2.2 GB ([ADR-0016](adr/0016-ci-ceiling-2-2-gb.md))
- [x] Image build in CI (arm64, GHCR, private) and sealed pull secrets per
      namespace — [ADR-0015](adr/0015-images-on-ghcr.md); sizes and the
      private-package check in [architecture.md](architecture.md) §9a, Images
- [x] **Pipeline heartbeat** — each successful run pings Healthchecks.io, a
      missing ping e-mails the operator
      ([ADR-0018](adr/0018-pipeline-heartbeat.md)); after a 90-minute failure
      on 2026-10-27 that alerted nobody. Verified 2026-10-27: staging on
      demand (`heartbeat sent: HTTP 200`), prod's 12:00 run (`ingest`,
      `transform` and `heartbeat` all exit 0, in 18 s)
- [ ] Runbook: disaster recovery and secret rotation — moved to M3: the
      move to the 8 GB node is the drill ([ADR-0022](adr/0022-platform-as-a-portfolio-of-architectures.md))

The Postgres backup left M2 on 2026-10-27
([ADR-0019](adr/0019-postgres-backup-deferred.md)): everything in Postgres today
is a copy of data USGS keeps, so a re-load rebuilds it. It enters by its
trigger in the table above — at the latest with Dagster's metastore in M3. The
mechanism and destination are still chosen then, measured on the node
([ADR-0012](adr/0012-cloudnative-pg.md)).

## M3 — The 8 GB node and Dagster

The node that M3 needs, and the orchestration every showcase uses.

- [x] **Move to `lagom-shared-02`** (8 GB) from Git and the runbook — this is
      the **disaster-recovery drill**: time each step, fix every gap the
      runbook shows, record the measured RTO
      ([ADR-0020](adr/0020-move-to-the-8-gb-node.md)). Done 2026-10-28: 20 min
      31 s from the first command on the node to prod's first green run
      ([runbook](architecture.md#disaster-recovery))
- [ ] Delete `lagom-shared-01` — by the checklist in the
      [runbook](architecture.md#retire-the-old-node)
- [x] Runbook: disaster recovery, written from the drill
- [ ] Runbook: secret rotation — the drill rotated nothing, so it is written
      when a credential is first rotated
- [x] Measure the new node's overhead and set its CI ceiling, as ADR-0016 did —
      1,687 MiB outside Kubernetes, ceiling 5.5 GB
      ([ADR-0024](adr/0024-ci-ceiling-on-the-8-gb-node.md)); re-measured after
      three days of uptime
- [ ] **Spike: the SME stack** — the USGS pipeline into DuckLake (Postgres
      catalog, data on R2) with dbt-duckdb; Evidence reading it; compaction of
      small files; memory and time against Postgres, including the Evidence
      build and the Pages deploy. Accept or revise
      ADR-0023 with the numbers
- [x] Postgres backup — before Dagster's metastore, whose run history exists
      only on the node. With the SME stack the state to protect is the catalog
      ([ADR-0019](adr/0019-postgres-backup-deferred.md)). Barman Cloud plugin
      to R2 ([ADR-0025](adr/0025-postgres-backup-barman-cloud-to-r2.md)), in
      staging and prod since 2026-10-28; a restore in staging was tested
      ([runbook](architecture.md#backup-and-restore-m3))
- [ ] Check backup retention on 2026-11-05: staging's 7-day retention must
      delete its first expired backup without error (ADR-0025 notes)
- [ ] Dagster with Postgres metastore
- [ ] dlt and dbt assets
- [ ] Native failure alerting
- [ ] `dbt test` in CI
- [ ] Freshness threshold declared and asserted
- [ ] Runbook: on-failure section

End of M3 = the backbone on its final node, orchestrated. **Natural checkpoint
to stop and reassess before adding anything.**

## M4 — getlagom.app

The platform's public face: a static site and a gallery of dashboards, with
the first showcase in it ([ADR-0022](adr/0022-platform-as-a-portfolio-of-architectures.md)). Public data, no login.

- [ ] Astro site on Cloudflare Pages at getlagom.app — design inspired by
      PostHog's; each page states the problem, then the solution
- [ ] Evidence dashboards built in the cluster by a Dagster step after each
      run and published to Cloudflare Pages, shown as a gallery of cards on the
      site ([ADR-0023](adr/0023-sme-stack-duckdb-on-ducklake.md), proposed)
- [ ] **Showcase: the SME stack on USGS** — the pipeline, with its real numbers
      (rows, run time, memory)
- [ ] **Showcase: the platform itself**, after the USGS showcase is live —
      infrastructure observability (node and pod memory against the budget,
      job durations, logs), with the stack in the
      [trigger table](#trigger-table) and its own ADR; the site shows exported
      snapshots, not a live dashboard

First thing worth showing.

## M5 — The SME stack at scale

The showcase the platform exists for: more data than the node has memory, on
the same SME stack — most of what is sold as big-data work does not need a
big-data stack ([ADR-0023](adr/0023-sme-stack-duckdb-on-ducklake.md), proposed).

- [ ] A public dataset larger than the node's memory, on the SME stack
- [ ] Benchmarks published: rows, gigabytes, time, peak memory — Postgres
      against DuckDB, local disk against R2 — with the method on the page
- [ ] Lakehouse trigger measures visible: `dbt run` duration and data size —
      [ADR-0008](adr/0008-postgres-for-all-layers.md)

## M6 — Streaming

Continuous events. Candidates in [`use-case-globe.md`](use-case-globe.md).

This is where the platform proves it grows by composition: **if adding a source
is only new configuration, the design worked.**

- [ ] Redpanda Connect with the source — if the source does not keep its
      history, the Postgres backup comes first
      ([ADR-0019](adr/0019-postgres-backup-deferred.md))
- [ ] Collector running on the Pi as an agent node. k3s currently advertises
      the node's public IP and runs flannel on the public interface; a node
      joining over Tailscale needs flannel on `tailscale0` (`node-ip`,
      `flannel-iface`) — settle it here
- [ ] NATS **only if** there is a second consumer or a replay requirement

> **Honest note:** if the source is GTFS-RT polled every 20 seconds, Redpanda
> Connect writes straight to the destination and NATS adds nothing functionally.
> Worth doing as a conscious learning exercise, not as a technical necessity.
> Knowing the difference is what prevents doing it to a real client.

## M7 — Two developers

Environments were pulled forward to M2 — see
[ADR-0007](adr/0007-three-environments.md). What remains is onboarding.

- [ ] Devcontainer, so both machines run an identical local environment
- [ ] Kubeconfig with per-developer RBAC
- [ ] Invite the second developer

## Track G — Agent guardrails

Cross-cutting, alongside the milestones: the guardrails that let agents build
the platform from prompts without quality dropping. The model and its rules are
in [ADR-0013](adr/0013-agent-driven-development-guardrails.md); each item enters
by its own trigger, like any other piece.

- [x] ADR-0013 accepted by the operator — 2026-10-16, with rule 2's fragility
      while the repository is private accepted as debt
- [x] **Secret scan in CI** (gitleaks) — the whole history on every pull
      request; one exception, for Sealed Secrets ciphertext, tested against
      plaintext in a sealed file. What it does not check is in
      [CONTRIBUTING](../CONTRIBUTING.md#secrets)
- [x] **Deny rules for destructive git** in `.claude/settings.json` — after an
      escape: the implementer discarded its own uncommitted work with
      `git checkout -- .` (archive PR #18). Claude Code cannot scope rules to one
      agent, so they bind every session; see
      [CONTRIBUTING](../CONTRIBUTING.md#workflow)
- [x] **Deny rules for cluster writes** — `kubectl` verbs that change or
      enter objects, file-based `create`, and `helm` writes are denied in
      `.claude/settings.json`; `create job --from=cronjob/…` stays allowed for
      on-demand runs. Triggered 2026-10-27, when agents first created Jobs to
      validate a promotion. What it does not stop is in
      [CONTRIBUTING](../CONTRIBUTING.md#workflow)
- [x] **Manifest policy check in CI**, in `tools/` beside the budget check:
      pinned chart and image versions, an explicit prune policy on every
      Application — with the next Argo CD Application (the Postgres `Cluster`).
      Its trigger was reached in M2, with the Postgres Applications. Done in [`tools/manifest_policy.py`](../tools/manifest_policy.py):
      the four rules and what the check does not cover are in
      [`tools/README.md`](../tools/README.md#manifest-policy-check). Required
      on `main` by the ruleset since 2026-10-27
- [ ] Data gates — `dbt test` and reconciliation in CI are M2 and M3 items
      above, not repeated here
- [x] **CI check that prod only pins a digest staging ran** —
      [`tools/promotion_check.py`](../tools/promotion_check.py): every prod
      image pinned by digest, and that digest pinned in staging on `main`
      before the change. "Pinned on `main`" stands in for "ran": CI never
      reaches the cluster ([ADR-0015](adr/0015-images-on-ghcr.md))
- [ ] **Post-deploy verification automated** (sync and health, memory against
      requests, error logs) — when the same manual check has been run after a
      third merge. **Trigger reached 2026-10-27:** Argo CD sync and health, the
      pinned digest in the CronJob, and a run's exit codes and dbt result were
      checked by hand after public PRs #7, #8, #11 and #12
- [x] **Branch protection** — ruleset on `main` since 2026-10-27, when the
      repository became public; what it enforces and what it does not is in
      [CONTRIBUTING](../CONTRIBUTING.md#branch-protection). The prerequisite
      for any agent merge
- [ ] First class of change merged by an agent (documentation is the
      candidate) — by the trigger in the table above

## Repository layout

Defined in [ADR-0006](adr/0006-monorepo-layout.md) and listed in
[`../README.md`](../README.md). Directories are created by the milestone that
fills them — no empty scaffolding.

| Directory | Born in |
|---|---|
| `docs/` | now |
| `platform/infra/`, `.github/` | M1 |
| `platform/warehouse/`, `services/usgs/` | M2 |
| `platform/orchestration/` | M3 |
| `products/` | M4 |

Argo CD watches `platform/infra/` only. GitHub Actions handles CI and consumes
nothing on the VPS.

**The test the layout must keep passing:** adding a source creates one directory
under `services/` and one under `platform/warehouse/models/`, and changes
nothing else. If a new source ever requires touching more, the layout needs
revisiting — with a new ADR.
