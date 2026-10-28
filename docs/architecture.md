# Architecture

Source of truth for how this platform is built. Read before touching any
component. Decisions with lasting consequence are recorded as ADRs in
[`adr/`](adr/); this document describes the resulting system.

---

## 1. Design principles

1. **Ephemeral compute.** The enemy is not tool size, it is resident RAM. Jobs
   start, process, and exit. We do not hold memory; we rent it by the second.
2. **Decoupled layers.** Storage, compute, transformation, and serving are
   replaceable pieces. This is what buys flexibility — swapping the compute
   engine touches neither ingestion nor consumers.
3. **Everything declarative in Git.** Infrastructure, ingestion,
   transformation, and reports are versioned code. No manual change in the
   cluster.
4. **Ingestion is configuration, not code.** A new source is new config, not a
   new script.
5. **Resource budget as a contract.** Memory requests and limits, and CPU
   requests, on every workload, with a CI check that fails if the sum exceeds
   the ceiling.
   **Frugal by design, not capped by the node.** The ceiling follows the
   node: moving to a bigger one is a resize and one number changed in §11, on
   the criteria in [ADR-0011](adr/0011-memory-viability-on-4gb.md). What does
   not change with the node is the discipline — every resident process
   justifies its memory, and work that can run as a job does not stay
   resident.
6. **Multi-dev from day one.** Nothing is built in a way that blocks a second
   developer from joining.
7. **Defer with a trigger.** Each piece enters when a concrete trigger appears,
   not because it is on the diagram. See [`roadmap.md`](roadmap.md).

## 2. Data flow

```
External sources (APIs, feeds, sensors)
        |
Ingestion — two patterns:
   batch/API  -> dlt (ephemeral job)
   event      -> Redpanda Connect [-> NATS]
        |
Postgres — bronze / silver / gold schemas
   transformation: dbt (ephemeral job; its SQL runs in Postgres)
        |
Access channels
```

**Proposed: the SME stack** ([ADR-0023](adr/0023-sme-stack-duckdb-on-ducklake.md), proposed). DuckDB as the engine, DuckLake as the
table format, Postgres as its catalog, the data files on Cloudflare R2. It
replaces the Postgres warehouse only after a spike in M3 passes; until then
every layer lives in Postgres ([ADR-0008](adr/0008-postgres-for-all-layers.md)).

Dagster orchestrates from the outside: it triggers jobs and records state,
lineage, and retries. It is not a step in the flow because data does not pass
through it.

## 3. Infrastructure

| Resource | Role |
|---|---|
| Hetzner CAX21 (4 ARM vCPU, 8 GB), `lagom-shared-02` in `fsn1` | control plane and main node; hosts the prod and staging namespaces since 2026-10-28 ([ADR-0020](adr/0020-move-to-the-8-gb-node.md)) |
| Hetzner CAX11 (2 ARM vCPU, 4 GB), `lagom-shared-01` in `nbg1` | the previous node, retired by the checklist in the runbook (*Disaster recovery*) |
| Raspberry Pi 3B (1 GB) | edge agent node, streaming collector |
| `getlagom.app` domain, registered and served by Cloudflare | public entry via Cloudflare (M4) |

Cost: the CAX11 was EUR 7.37/month, as shown in the Hetzner Console on
2026-10-12 ([ADR-0002](adr/0002-single-node-k3s-hetzner.md)); the CAX21 is
roughly double ([ADR-0020](adr/0020-move-to-the-8-gb-node.md)), its exact
price the one the Console shows. Object storage (R2) enters with the SME-stack
spike in M3, on its free tier ([ADR-0023](adr/0023-sme-stack-duckdb-on-ducklake.md), proposed); the prices checked earlier are in ADR-0008.

**Outside the cluster, principle 3 does not hold yet.** The server, its
firewall, the Tailscale ACL, and the Healthchecks.io checks are created by
hand, following the runbook (§13); the domain's zone at Cloudflare was set up by
hand in its console, and Cloudflare Access does not exist yet (it enters by
trigger, with the first content that must not be public). Argo CD
reconciles only what runs inside the cluster. Terraform takes over these
resources by trigger — see [`roadmap.md`](roadmap.md#trigger-table).

### Kubernetes — k3s

k3s is CNCF-certified Kubernetes, not a reduced variant: same API, same
manifests, same `kubectl`. See [ADR-0002](adr/0002-single-node-k3s-hetzner.md).

Three k3s defaults to be aware of, so they are not mistaken for upstream
behaviour:

| Default | Market standard | Our choice |
|---|---|---|
| Traefik as ingress | ingress-nginx | **disabled**: nothing uses an ingress, and servicelb published it on the public address ([ADR-0021](adr/0021-k3s-packaged-components-under-git.md)) |
| local-path storage | a real CSI driver | fine on a single node; volume is pinned to the node. Installed by Argo CD, not as a k3s addon ([ADR-0021](adr/0021-k3s-packaged-components-under-git.md)) |
| SQLite datastore | etcd | no HA; k3s can run embedded etcd if needed |

None of this appears in our manifests. Deployments, Services, RBAC, CRDs,
Secrets, and Argo CD itself are identical to any Kubernetes.

### GitOps — Argo CD

Git as the source of truth, continuous reconciliation. Dex (SSO) is disabled to
save memory. Secrets never go to Git in plain text — they are sealed with
Sealed Secrets ([ADR-0010](adr/0010-sealed-secrets.md)).

**Reconciliation** is the loop that makes this work: every few minutes Argo CD
compares what `main` says should exist with what runs in the cluster, and
changes the cluster until they match. A manual change in the cluster is undone
on the next pass (`selfHeal`); an object removed from Git is deleted from the
cluster (`prune`).

**App of apps.** A `root` Application watches `platform/infra/apps/` and creates
every Application found there; each Application points at a directory or a Helm
chart. Argo CD manages itself the same way, from a pinned upstream chart and
[`platform/infra/argocd/values.yaml`](../platform/infra/argocd/values.yaml). It
reads this public repository anonymously over HTTPS. See
[ADR-0009](adr/0009-argocd-bootstrap-and-self-management.md) and
[ADR-0017](adr/0017-public-repository-from-a-snapshot.md).

## 4. Ingestion — two patterns

| Source nature | Tool |
|---|---|
| Batch API with incremental state | **dlt** as a job/asset |
| Continuous events (MQTT, websocket, GTFS-RT) | **Redpanda Connect** -> NATS |

Not duplication: two shapes of problem. See
[ADR-0003](adr/0003-ingestion-split-dlt-benthos.md).

### dlt — batch

dlt is a library, not a server: it runs inside the job and exits. Zero resident
RAM, which matches the ephemeral compute principle.

It natively solves the five points where a streaming tool is weak at batch
extraction: pagination; incremental state across runs; schema inference and
evolution; normalization of nested JSON; and backfill.

The `rest_api` source declares endpoints, paginator, auth, and incremental
cursor as data, keeping "ingestion is configuration" true.

It integrates natively with Dagster, so each pipeline becomes an asset with
lineage and no glue code.

The `rest_api` config lives in a YAML file next to the pipeline, loaded with
`yaml.safe_load`. The first source is [`services/usgs`](../services/usgs/README.md).

### Redpanda Connect — events

Go binary, roughly 80 MB resident. Declarative YAML: input, pipeline, output.
Connectors for most transports, including MQTT, which matters for future IoT
sources.

### NATS JetStream — deferred

CNCF, roughly 40 MB, with persistence, replay, and consumer groups. **Deferred
with a trigger:** if a source is polled every 20 seconds, Redpanda Connect can
write straight to the destination and NATS adds nothing functionally. It earns
its place with multiple consumers or a replay requirement. Building it earlier
is a deliberate learning exercise, labelled as such — not a technical necessity.

## 5. Storage — Postgres now, open table format by trigger

**Now:** bronze, silver, and gold are schemas in each environment's Postgres.
Bronze is append-only, so a transformation is replayed by re-running dbt, never
by re-reading the source. dlt normalizes nested JSON into typed child tables;
objects nested beyond `max_table_nesting` are kept as `JSONB`. Binary payloads
are not stored in Postgres — a source that carries files is a lakehouse
trigger. See [ADR-0008](adr/0008-postgres-for-all-layers.md).

**When the lakehouse enters**, the rest of this section applies.

Plain Parquet is good at reading and writing but has no transactions, no
updates, and no controlled schema evolution. For multi-source and IoT that hurts
quickly: late data, record corrections, a sensor that gains a field.

A table format provides ACID over files, time travel, schema evolution, and real
`MERGE`.

**Iceberg is the preference; Delta is the fallback. Decided by testing when
the lakehouse enters** — see [ADR-0004](adr/0004-table-format.md). **Proposed
change:** for the SME stack, [ADR-0023](adr/0023-sme-stack-duckdb-on-ducklake.md), proposed puts DuckLake in place of Iceberg, with a
catalog in Postgres; Iceberg stays the table format of the big-data stack.

**Rule for this phase, to avoid overengineering:** no catalog, no optimization,
no snapshot maintenance. Write and read by path only.

## 6. Transformation — dbt

**Now:** `dbt-postgres`. The container starts, runs `dbt run`, and exits; the
SQL executes inside the environment's Postgres. The job has no idle cost, but
the work lands on a resident process that also serves reads — the trade-off
ADR-0008 accepts, and whose limit is the first lakehouse trigger. Models prefer
portable SQL, because a later move to DuckDB has to port them.

**Proposed, with the SME stack** ([ADR-0023](adr/0023-sme-stack-duckdb-on-ducklake.md), proposed): `dbt-duckdb` on DuckLake.

**When the lakehouse enters:** DuckDB reads the table format directly from
object storage, processes with a configured `memory_limit` (spilling to disk
rather than dying), and writes back. Compute becomes fully ephemeral.

Layers: bronze (raw, typed), silver (cleaned, conformed), gold (modelled for
consumption). Each layer's guaranteed schema is a contract — see
[`engineering-protocol.md`](engineering-protocol.md) §16.3.

**The project** is `platform/warehouse/`. For USGS, silver is
`stg_usgs__events` (the latest revision of each event, typed, times in UTC) and
gold is `fct_earthquakes` (earthquakes only, with magnitude and depth classes —
the USGS showcase's main table) and `agg_earthquakes_daily_region`. Both gold models have an
enforced contract. `dbt build` runs the tests with the models: keys, ranges and
accepted values; reconciliation of row counts between the layers
(`tests/reconcile_*.sql`); and unit tests of the dedup, the region parsing and
the class boundaries. Freshness of bronze (warn 2 h, error 6 h) is checked by
`dbt source freshness`. CI lints and parses the project but runs no model: how
to run it is in [`platform/warehouse/README.md`](../platform/warehouse/README.md).

## 7. Orchestration — Dagster

Assets, lineage, backfill, declarative retries, native dbt and dlt integration.
Metastore in Postgres, since the SQLite default does not serve multiple users.

**One instance per environment** ([ADR-0026](adr/0026-dagster-one-instance-per-environment.md)),
in the environment's namespace, with its metadata in a database `dagster` in
that environment's Postgres, backed up with it. Runs are Kubernetes Jobs in
the same namespace, so staging never reaches prod.

**One code location for the platform**, the image `lagom-orchestration`
([`platform/orchestration/`](../platform/orchestration/README.md)). It holds
each service's assets (`services/<service>/assets/`) and the dbt project,
whose models dagster-dbt turns into assets downstream of the sources they
read. Its first content is USGS on DuckLake:

- the job `usgs` every 30 minutes: dlt loads into DuckLake, then `dbt build`
  runs on the `lake` target;
- the job `lake_maintenance` once a day: it merges small files, expires
  snapshots older than 7 days, and deletes the files nothing references.

Until Dagster takes over the alarm, the CronJobs keep running and each run
reports success to Healthchecks.io, which e-mails the operator when a report
is missing ([ADR-0018](adr/0018-pipeline-heartbeat.md); runbook: *Pipeline
heartbeat*).

Airflow and Prefect are excluded on resident RAM.

## 8. Serving — Postgres

Postgres is the operational spine, with two permanent roles independent of
geographic data:

1. **Metastore** for Dagster (run history, asset state).
2. **Serving layer** for dashboards, API, and BI — concurrent reads, low
   latency.

PostGIS is a bonus when data is geographic and leaves the picture when it is
IoT. See [ADR-0005](adr/0005-duckdb-and-postgres-roles.md) for why DuckDB does
not take this role.

**How it runs: CloudNativePG** ([ADR-0012](adr/0012-cloudnative-pg.md)). An
operator in `cnpg-system` reconciles each committed `Cluster` object into
Postgres Pods, disks, Services, and credentials. Roles, databases, and the
pooler are declared the same way when their triggers arrive.

**Backup** ([ADR-0025](adr/0025-postgres-backup-barman-cloud-to-r2.md)): the
Barman Cloud plugin, running beside the operator, archives every WAL segment
and takes a daily base backup into an R2 bucket per environment. Each Cluster
names an `ObjectStore` in `spec.plugins`, and the plugin adds a sidecar to its
Pod. Staging and prod each have their own bucket; procedures are in the
runbook's *Backup and restore*. cert-manager issues the TLS certificates the plugin and
the operator use.

**Credentials.** The prod `Cluster` ([`platform/infra/postgres-prod/`](../platform/infra/postgres-prod/cluster.yaml))
creates the `lagom` database and role, and the operator generates that role's
password into the Secret `postgres-app` in the `prod` namespace. Nothing is
sealed or committed to Git. Consumers read their credentials from that Secret
and must not cache the password: on a rebuild of the cluster a new one is
generated. No superuser password is exposed (`enableSuperuserAccess: false`).

Until the lakehouse trigger it has a third role: **storage and transformation
engine for every layer** ([ADR-0008](adr/0008-postgres-for-all-layers.md)).
Afterwards it returns to holding only the small final result, with raw history
in the table format.

**PgBouncer** — deferred with a trigger: it enters with the first external BI
consumer. Each Postgres connection costs 5–10 MB, and BI tools open them
freely; without pooling a 300 MB Postgres becomes 1 GB. It comes as a
CloudNativePG `Pooler` object, not a separate install.

## 9. Visualization

The public face is static: nothing on the node serves it
([ADR-0022](adr/0022-platform-as-a-portfolio-of-architectures.md)).

| Tool | Role | RAM on the node | Enters when |
|---|---|---|---|
| **Astro** | the site at getlagom.app: pages, copy, the gallery of showcases | 0 (static, Cloudflare Pages) | M4 |
| **Evidence** | the dashboards: SQL + Markdown, charts built on Apache ECharts, built by a Dagster step in the cluster after each run | 0 resident (an ephemeral build job) | M4 |
| **Streamlit** | interactive apps | 200–250 MB | an app a static page cannot serve |
| **Grafana** | time series, pipeline health, alerting — for the operator, over the tailnet | 150 MB | with infrastructure observability, after the USGS showcase is live ([roadmap](roadmap.md#trigger-table)); the stack's other components are not in §11 until measured |

How a dashboard is published: a Dagster step after each run builds Evidence in
the cluster and deploys the static pages to Cloudflare Pages, an outbound
connection, so the site follows the data ([ADR-0023](adr/0023-sme-stack-duckdb-on-ducklake.md), proposed). A visitor never reaches the
cluster.

Evidence is MIT-licensed with no per-seat cost. It is built for reviewed
reports, not ad-hoc exploration. Its npm releases paused between February and
October 2026; the exit is the Observable Framework, which keeps the SQL and the
Parquet ([ADR-0022](adr/0022-platform-as-a-portfolio-of-architectures.md)).

Two cautions: in static build mode the data is **embedded in the site** as
Parquet, and Evidence has **no authentication and no row-level security**. A
public showcase therefore publishes only public data. Private data means one
build per audience behind Cloudflare Access — not a permission inside the app.

Metabase, Superset and Lightdash are the self-service BI options, at 600 MB to
1 GB or more each. They enter when a client needs ad-hoc exploration, behind
login.

## 9a. Environments

Three, decided in [ADR-0007](adr/0007-three-environments.md).

| Environment | Where | What runs there |
|---|---|---|
| `dev` | code on the operator's machine, data in staging | dbt and dlt run from the machine's `uv` environments against the `lagom_dev` database in staging's Postgres, through `kubectl port-forward` over the tailnet; unit tests need no database; manifests are checked with a server-side dry run ([ADR-0014](adr/0014-develop-against-staging.md)); agents use `kubectl diff -n <namespace> -f`, since `apply` is denied to them ([CONTRIBUTING](../CONTRIBUTING.md#workflow)) |
| `staging` | namespace on the node | own Postgres `Cluster` mirroring prod's configuration, holding two databases: `lagom` for staging's pipeline and `lagom_dev` for the developer, who cannot connect to `lagom`; own secrets; a ResourceQuota (768Mi of memory requests, 1536Mi of limits, 10 Pods) and a LimitRange ([`platform/infra/postgres-staging/`](../platform/infra/postgres-staging/)); the pipeline as one CronJob, `usgs-pipeline` ([`cronjob-usgs.yaml`](../platform/infra/postgres-staging/cronjob-usgs.yaml)): dlt, then dbt, as init containers, then a heartbeat ping to Healthchecks.io ([ADR-0018](adr/0018-pipeline-heartbeat.md)), applied by Argo CD from `main` and pinned to staging's image digests ([ADR-0015](adr/0015-images-on-ghcr.md)). **No Dagster** ([ADR-0007](adr/0007-three-environments.md)); on the 4 GB node a second orchestrator exceeded the ceiling, and on the 8 GB node that reason is to be revisited when Dagster enters |
| `prod` | namespace on the node | the full stack |

**Promotion** is by image digest: staging and prod each pin their own, so a new
image reaches staging through one pull request and prod through another, both
from `main` ([ADR-0015](adr/0015-images-on-ghcr.md)). CI enforces the order:
[`tools/promotion_check.py`](../tools/promotion_check.py) fails a change whose
prod manifests pin an image without a digest, or a digest staging had not
pinned on `main` before that change — Postgres's `imageName` included. It
cannot see whether staging's run succeeded; the operator confirms that before
opening the prod pull request. Beside it,
[`tools/manifest_policy.py`](../tools/manifest_policy.py) fails an Application
with no explicit `prune`, a chart not pinned to an exact version, a Git source
outside this repository, or a rendered image without a tag or digest (this
repository's own images need a digest); what it does not check is in
[`tools/README.md`](../tools/README.md#manifest-policy-check).

**Images.** Three, built by [`images.yml`](../.github/workflows/images.yml) on a
native arm64 runner:

- `ghcr.io/filipefantini/lagom-usgs`: the dlt pipeline,
  [`services/usgs/Dockerfile`](../services/usgs/Dockerfile).
- `ghcr.io/filipefantini/lagom-warehouse`: `dbt build`,
  [`platform/warehouse/Dockerfile`](../platform/warehouse/Dockerfile).
- `ghcr.io/filipefantini/lagom-orchestration`: the Dagster code location,
  [`platform/orchestration/Dockerfile`](../platform/orchestration/Dockerfile).
  It is built from the repository root. A pull
request builds and smoke-tests them without pushing; a push to `main` publishes
them tagged with the commit SHA, and the digest is printed in the run summary.
Both are multi-stage (uv exists only in the build stage), pinned by digest at
the base, run as UID 10001 on a read-only root filesystem, and write only under
`/tmp`: mount an `emptyDir` there. Measured on the first build (archive PR #27,
2026-10-17): `lagom-usgs` 206 MiB, `lagom-warehouse` 397 MiB, built in 40 and
52 s. Both packages are private: an anonymous manifest request to ghcr.io
returns HTTP 403 (checked 2026-10-17; the same request against a public image
succeeds). Staging's and prod's CronJob `usgs-pipeline` runs them
every 30 minutes, dbt starting only if the load exited 0: both are init
containers, and a `heartbeat` container pings Healthchecks.io only if both
exited 0 ([ADR-0018](adr/0018-pipeline-heartbeat.md)). It pulls from GHCR with
the sealed `ghcr-pull` Secret, which the operator adds to the same directory.

Staging is real rather than nominal because of four enforced conditions: its own
Postgres pod and credentials, a ResourceQuota and LimitRange, a NetworkPolicy
denying staging to prod, and separate secrets. A staging that shares prod's
database would prove nothing.

Staging is recreated on demand before structural infrastructure changes, not on a
schedule.

**Accepted limitation:** neither environment is isolated from node failure or
global memory pressure. The trigger for a second VPS is a real client.

## 10. Access channels

Progressively less privileged. Any new access request is answered by choosing
one of the three.

| Channel | Who | What it grants |
|---|---|---|
| **Public site** (getlagom.app) | anyone | static pages and dashboards of public data; no path to the cluster |
| **Tailscale** | operators and admin | raw Postgres and the whole cluster |
| **Cloudflare Access** | partners, cloud BI | report reading via browser, no install |
| **Signed file URL** | partners, external pipelines | bytes with an expiry, access to nothing |

### Node shell (SSH)

Not an access channel: a break-glass path for administering the node itself —
installing k3s, upgrading the OS. Day-to-day work never needs it: changes reach
the cluster through a pull request and Argo CD, and inspection goes through
`kubectl` over Tailscale with per-developer RBAC (M7).

- **Personal accounts only.** One Linux user per person, with their own key. A
  shared account makes the log say what happened but not who did it, and
  revoking one person means rotating everyone's key.
- **`sudo` for operators only.** A developer who ever needs a shell gets a user
  outside the `sudo` group.
- Root login and password authentication are disabled; `AllowUsers` lists every
  permitted account explicitly. See the provisioning steps in §13.
- **Reachable only over Tailscale.** The node has no inbound port open to the
  internet; the break-glass path is in the runbook (§13).

### Tailscale

WireGuard mesh, ACL by identity, **no open ports**. Headscale is the
self-hosted control plane if a fully open-source server is required — the
Tailscale client is already open source.

### Cloudflare Tunnel + Access

Deferred with a trigger: enters with the first content that must not be
public ([ADR-0022](adr/0022-platform-as-a-portfolio-of-architectures.md)). A light
agent (`cloudflared`, ~30 MB) opens an **outbound-only** connection. Access puts
identity in front with per-application policy. The partner gets a link, logs in,
and sees the dashboard — no install, with WAF and rate limiting included.

### Signed URL

**Requires object storage, so it is unavailable until R2 enters (M3, if the
SME-stack spike passes)**
([ADR-0008](adr/0008-postgres-for-all-layers.md)); a consumer that needs it is
itself one of the triggers.

An HMAC over a single object with an embedded expiry, verified by the storage
layer. This is the same mechanism Delta Sharing uses underneath.

**It carries no identity authentication.** Within the TTL, whoever holds the
link has access, and it cannot be revoked before expiry. Therefore: short TTL
(hours, not weeks), one URL per recipient, and emission logged.

Natural evolution: when auditing and revocation are needed, a minimal endpoint
validates a JWT and mints the URL on demand.

### Permission model — one for all channels

| Control | When |
|---|---|
| Read-only role per consumer, `GRANT` on the `gold` schema only | from the start; it is trivial |
| Row Level Security for per-client isolation, enforced by the database | trigger: second consumer with segregated data |
| PgBouncer in front | trigger: first external BI |

**How the read-only role is built.** Each `Cluster` declares a group role,
`gold_reader`: NOLOGIN, so it cannot connect, and no attribute beyond the
default. Its privileges come from dbt (`platform/warehouse/dbt_project.yml`),
which grants `SELECT` on every gold model and `USAGE` on the `gold` schema each
time it builds one, since a rebuilt table loses the grants of the one it
replaces; a missing role fails the build. An environment holds these grants
only once its CronJob pins a warehouse image built with that configuration;
until then the role exists there and can read nothing. A data test checks the outcome in the
catalogue: gold readable, bronze and silver not, nothing writable
([warehouse README](../platform/warehouse/README.md)). A consumer gets its own login role inside that group
(`inRoles: [gold_reader]` in the `Cluster`, with its own sealed password), so
each one is revoked alone. No consumer exists yet, so no login role does.

RLS with a single user is theatre, so it is not required in the first commit.
The underlying argument still holds: when PostgREST arrives it maps JWT claims
to Postgres roles, which trigger the same policies. Model once, serve four
channels.

### Why the API, not the database, is the public channel

The asymmetry is structural:

1. **Where authentication happens.** With an API, the proxy terminates TLS and
   rejects the unauthenticated before anything reaches the application. With
   Postgres, the database itself parses the initial packet — the attack surface
   *is* the database.
2. **What is exposed.** An API exposes defined endpoints. Postgres exposes an
   **arbitrary query engine**: whoever authenticates writes any SQL, including
   one that consumes the whole CPU. RLS limits rows, not cost.
3. **Defensive ecosystem.** HTTP has WAF, rate limiting, OAuth, bot detection.
   The Postgres wire protocol has almost none of it.
4. **Credentials.** An API token is scoped, short-lived, and revocable. A
   database password saved in a BI connection is long-lived and stored
   somewhere unknown.

PostgREST is the planned API: it reads the schema and **generates the REST API
itself** — no code, just configuration, around 50 MB, with authorization via
RLS.

## 11. Resource budget

The node, `lagom-shared-02`, shows **7,741 MiB** of RAM to the OS (the rest of
the nominal 8 GB is reserved by firmware and kernel). Two budgets share it,
kept apart because they are enforced differently.

### Node overhead — outside Kubernetes, enforced by nothing

**On `lagom-shared-02`**, 2026-10-28, two hours after k3s started, 12 Pods
running: **1,687 MiB** by RSS — `k3s-server` 1,022, `containerd` 200, 12 shims
254, `tailscaled` 55, the rest of the OS ~156
([ADR-0024](adr/0024-ci-ceiling-on-the-8-gb-node.md)). It is to be measured
again after at least three days of uptime.

**On `lagom-shared-01`**, the 4 GB node, the history behind those figures —
measured from 2026-10-12, first with the cluster idle and only k3s's own
system pods running (RSS from `ps`):

| Process | Measured | Earlier estimate |
|---|---|---|
| `k3s-server` — API server, controllers, scheduler, kubelet, kube-proxy, flannel, network policy controller, and the SQLite datastore in one process | 627 MB fresh; 1,235 MB after 17 h; ~730 MB with `GOMEMLIMIT=600MiB`, 761 MiB after 67 h; **983 MiB with `GOMEMLIMIT=900MiB`** on 2026-10-17, after 600MiB caused GC thrash ([ADR-0011](adr/0011-memory-viability-on-4gb.md) notes) | 300 MB "k3s" |
| `containerd` + one shim per running pod | ~265 MB with 7 pods; **~473 MiB with 14** (2026-10-17) | not counted |
| `tailscaled` | 47 MB | "negligible" |
| sshd, journald, rest of the OS | ~20 MB | not counted |
| **Total** | ~1.1 GB in M1; **~1.5 GB** on 2026-10-17 (RSS, overstated by shared pages; 1,622 MiB available on the node) | **0.3 GB** |

Without a memory limit, Go lets the heap grow to about twice its live size and
keeps idle memory from the OS; `GOMEMLIMIT` on every resident Go process is the
largest lever found ([ADR-0011](adr/0011-memory-viability-on-4gb.md)).

The estimate of 300 MB was the commonly quoted figure for k3s; on the 4 GB
node the server process alone was twice that, and the container runtime was missing from
the count. RSS overstates slightly because shared pages are counted per process;
it is the conservative measure.

### Pod requests — the CI ceiling

**Ceiling enforced in CI: 5.5 GB of declared requests.** A change that would
exceed it fails the build — see
[`engineering-protocol.md`](engineering-protocol.md) §16.5. The arithmetic,
from the overhead above: 7,741 MiB visible − 1,687 MiB outside Kubernetes
leaves ~6,050 MiB for pods; the ceiling (5,632 MiB) sits ~420 MiB under that,
for k3s's growth over days and the shims of new Pods, which requests do not
count ([ADR-0024](adr/0024-ci-ceiling-on-the-8-gb-node.md)). It was 2.2 GB on
the 4 GB node ([ADR-0016](adr/0016-ci-ceiling-2-2-gb.md)), where M3 did not
fit, hence the move ([ADR-0020](adr/0020-move-to-the-8-gb-node.md)). Today's
total is 2,398 MiB; M3 with Dagster is about 3,000.

**How CI enforces it.** [`tools/resource_budget.py`](../tools/resource_budget.py)
runs on every pull request ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)).
It renders every Application the way Argo CD does and fails if any container
lacks a memory request, a memory limit, or a CPU request (for a CloudNativePG
`Cluster`, whose Pods the operator creates, its `spec.resources` and
`spec.instances` stand in for the Pod spec, plus the Barman Cloud sidecar
declared on the `ObjectStore` it names), or if the total
exceeds the ceiling above, which it reads from this file. The total is resident
requests, plus **every ephemeral job at once**, plus an **allowance for
components k3s installs outside Git**.

**Known exception: CoreDNS.** Since [ADR-0021](adr/0021-k3s-packaged-components-under-git.md)
it is the only component k3s still installs: Traefik and servicelb are
disabled, and local-path and metrics-server are Argo CD Applications that the
check counts like any other. CoreDNS is outside Git, so the check cannot see
it, but it declares a request (70 MiB) and a limit (170 MiB), and the check
adds that 70 MiB request as its allowance for components outside Git.

**Core (M1–M3)** — workloads that run as pods:

| Component | Request | Source |
|---|---|---|
| kube-system (CoreDNS, metrics-server) and local-path | ~215 MB | requests: CoreDNS 70, metrics-server 80, local-path 64 MiB; Traefik disabled ([ADR-0021](adr/0021-k3s-packaged-components-under-git.md)). Measured 2026-10-27: 71, 73 and 47 MiB |
| Argo CD (no Dex) | 608 MB | set from measurement with three Applications: application-controller 290–465 MiB before `GOMEMLIMIT`, 190–285 MiB after (request 384, limit 640, `GOMEMLIMIT` 540MiB), repo-server ~105, server ~37, redis ~10 ([ADR-0009](adr/0009-argocd-bootstrap-and-self-management.md)) |
| CloudNativePG operator | 64 MB | measured 24 MiB with no Cluster, 31 MiB reconciling one (request 64, limit 192, `GOMEMLIMIT` 150MiB) ([ADR-0012](adr/0012-cloudnative-pg.md)) |
| Backup: Barman Cloud plugin and cert-manager | 192 MB | plugin 32, cert-manager controller 64, cainjector 64, webhook 32; each with `GOMEMLIMIT`; measured idle on 2026-10-28: 19, 34, 31 and 17 MiB ([ADR-0025](adr/0025-postgres-backup-barman-cloud-to-r2.md)). Each backed-up Postgres instance adds a 64 MiB sidecar (18 MiB measured during a base backup), counted with its Cluster |
| Postgres (prod `Cluster`, 1 instance) | 364 MB | 300 for Postgres plus 64 for the backup sidecar. Postgres: request 300 MiB, limit 512 MiB; `shared_buffers` 96MB, `max_connections` 25, `work_mem` 4MB, `maintenance_work_mem` 32MB, `effective_cache_size` 256MB, instance manager `GOMEMLIMIT` 96MiB. Measured idle on 2026-10-16: pod working set 47 MiB, cgroup 55 MiB (25 anonymous, 25 page cache), instance manager ~62 MiB RSS including shared pages. The request is kept for dbt load, measured in M2. Counted by the CI check, which reads the `Cluster` object because the operator creates its Pods ([`platform/infra/postgres-prod/`](../platform/infra/postgres-prod/cluster.yaml)) |
| Dagster | 600 MB | measured in a spike: ~550 MiB resident with real libraries ([ADR-0011](adr/0011-memory-viability-on-4gb.md)) |
| **Core requests** | **~2.04 GB** | |
| **Left within the ceiling for ephemeral jobs** | **~3.5 GB** | |

Staging adds ~364 MB for its own Postgres
([ADR-0007](adr/0007-three-environments.md)): a second `Cluster` with the same
request and limit as prod's, plus the 64 MiB backup sidecar, which the CI
check counts like the first
([`platform/infra/postgres-staging/`](../platform/infra/postgres-staging/cluster.yaml)).
That leaves **~3.1 GB** for jobs. Staging's ResourceQuota caps what its jobs
can request at 768 MiB in all, Postgres included.
dlt and dbt do not appear above: they are ephemeral jobs, and their requests
count against what is left. In staging they are one Pod, the CronJob
`usgs-pipeline`: dlt and dbt each request 256 MiB and run one after the other
as init containers, and the `heartbeat` container requests 32 MiB, so the Pod
requests 256 MiB, not 544 (a Pod's request is the larger of its biggest init
container and the sum of its regular ones). Prod runs the same Pod on the same schedule, so at :00 and :30 both
are placed together, and a run started by hand can land on either. The CI
check therefore adds every ephemeral job rather than taking the largest: until
2026-10-19 it took the largest, which left out the second pipeline's 256 MiB
and the 32 MiB Job that the Argo CD chart runs as a hook on its syncs. The
total rose by 288 MiB, to 2,034 of the 2,253 MiB ceiling of the time. The sum overstates
jobs whose schedules never meet, which is the safe error for a memory gate.
The 256 MiB is a starting
value. First scheduled run, 2026-10-18 20:30 (8 new events, 15 s): one
kubelet sample per container gave dlt ~60 MiB and dbt ~151 MiB — a floor,
not a peak, since the stats refresh every ~10 s; the request stays until a
longer run is sampled. dbt's SQL runs inside Postgres while every layer
lives there ([ADR-0008](adr/0008-postgres-for-all-layers.md)). Sealed Secrets
declares 32 MB and uses 16 MiB measured ([ADR-0010](adr/0010-sealed-secrets.md)), small enough to leave
the totals above unchanged at this precision. The Evidence build is an
ephemeral job, measured in the SME-stack spike.

**Full design**, adding what enters by trigger:

| Addition | RAM |
|---|---|
| NATS + Redpanda Connect | 120 MB |
| Streamlit | 250 MB |
| Grafana | 150 MB |
| PgBouncer | 5 MB |
| **Core + staging + additions** | **~2.9 GB of requests** |
| **Left within the ceiling for ephemeral jobs** | **~2.6 GB** |

On the 4 GB node the full design left no room for jobs, which is why the
platform moved to the CAX21 ([ADR-0020](adr/0020-move-to-the-8-gb-node.md)).
On the 8 GB node it fits with about 2.6 GB to spare; that room is the margin
the node allows, not a budget to fill (§1).

## 12. Accepted risks

- **No high availability.** A single node; maintenance takes everything down.
  Acceptable at this stage, but it is a choice, not an oversight.
- **The Pi's SD card is a worse bottleneck than its RAM.** No USB3, and constant
  writes kill cards in months. Local disk is never a hot layer.
- **Swap is a trap.** With swap on SD the system does not die, it becomes slow
  enough to look dead — harder to debug. Better to cap pod memory and let the
  OOM killer act quickly and explicitly.
- **etcd on shared vCPU is sensitive** (it depends on fast fsync). Relevant if
  HA or Talos is ever adopted.
- **Scaling.** Vertical is easy — Hetzner resizes, one reboot. Horizontal needs
  care with the datastore (SQLite to etcd, three nodes) and with storage
  (local-path pins the volume to a node; either node affinity or Longhorn).
- **Postgres backup: paid on 2026-10-28, with two open checks.** The debt
  accepted in [ADR-0019](adr/0019-postgres-backup-deferred.md) is paid by
  [ADR-0025](adr/0025-postgres-backup-barman-cloud-to-r2.md): both
  environments archive WAL and take daily backups to R2, and a restore was
  tested (runbook, *Backup and restore*). Two things are still unproven.
  Retention deleting expired backups can only be checked from 2026-11-05. A
  rebuild of the node that restores from the bucket, instead of re-loading,
  has not been run.
- **Changes to the gates themselves are protected by convention only.**
  Branch protection (since 2026-10-27) requires the checks to pass, but a pull
  request runs the workflow as it edits it — see
  [CONTRIBUTING](../CONTRIBUTING.md#branch-protection).

## 13. Runbook

Operational procedures. **Kept current as part of any change that affects how
the platform is run or recovered** — see [`CLAUDE.md`](../CLAUDE.md) §5.

**Placeholders.** The repository is public, so values that identify the
operator or address the node are written in angle brackets and never filled
in here ([ADR-0017](adr/0017-public-repository-from-a-snapshot.md)):
`<admin-user>` (the node's login user), `<operator-ssh-public-key>` (from
1Password), `<operator-tailscale-login>` (the identity the operator signs in to
Tailscale with), `<tailnet>` and `<node-tailnet-ip>` (both printed by
`tailscale status`), and `<ip>` / `<public-ip>` / `<public-ipv4>` (the Hetzner
Console). `<node-name>` is not a secret but changes with each node: it is
`lagom-shared-02` since 2026-10-28, and the next node takes the next index;
`<old-node-name>` is the one being replaced.

### Provision the node (M0)

Hetzner Console → Add Server, with the settings in
[`roadmap.md`](roadmap.md#provisioning-settings). Two fields matter beyond the
table:

- **SSH keys:** select the operator's key. It lands in root's
  `authorized_keys`, which the cloud-config below makes unusable — but with no
  key selected, Hetzner generates a root password and emails it, and that
  password should never exist.
- **Cloud config:** paste the block below, including the `#cloud-config` first
  line; without it cloud-init ignores the content.

```yaml
#cloud-config
users:
  - name: <admin-user>
    groups: [sudo]
    shell: /bin/bash
    lock_passwd: true
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    ssh_authorized_keys:
      - <operator-ssh-public-key>
disable_root: true
ssh_pwauth: false
write_files:
  - path: /etc/ssh/sshd_config.d/10-hardening.conf
    content: |
      PermitRootLogin no
      PasswordAuthentication no
      KbdInteractiveAuthentication no
      AllowUsers <admin-user>
runcmd:
  - systemctl restart ssh
```

**Why it works.** The cloud-config is the server's *user data*: Hetzner stores
it once, at creation, and serves it from the metadata endpoint
(`169.254.169.254`). On first boot cloud-init reads it and applies it. It is
therefore fixed at creation — a Rebuild re-runs cloud-init with the **original**
user data, so changing it means creating a new server.

**Never set `disable_root: true` without creating a user.** cloud-init then
replaces root's key with a forced command that only prints
`Please login as the user "NONE"`, and the node is unreachable. This happened on
the first attempt and cost a server recreation.

`NOPASSWD` is required because the user has no password (`lock_passwd`). The
accepted trade-off: whoever holds the SSH key has root. The key lives in
1Password and port 22 is open only to the operator's IP.

**Verify** — the host key changes on every creation, so remove the old entry
and compare the new fingerprint before trusting it:

```bash
ssh-keygen -R <ip>
ssh <admin-user>@<ip> 'sudo -n true && cloud-init status --long'
ssh <admin-user>@<ip> 'sudo sshd -T' | grep -E '^(permitrootlogin|passwordauthentication|kbdinteractiveauthentication|allowusers) '
ssh root@<ip> true
```

Expected: `status: done` with `errors: []`; `permitrootlogin no`,
`passwordauthentication no`, `kbdinteractiveauthentication no`,
`allowusers <admin-user>`; and root refused with `Permission denied (publickey)`.

### Join the tailnet (M1)

On the node, from Tailscale's official Debian repository:

```bash
curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.noarmor.gpg \
  | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.tailscale-keyring.list \
  | sudo tee /etc/apt/sources.list.d/tailscale.list
sudo apt-get update && sudo apt-get install -y tailscale
sudo tailscale up --hostname=<node-name>
```

`tailscale up` prints a login URL. The operator opens it, signs in, and approves
the machine. **No auth key is involved**, so no credential passes through a
script or a chat. The trade-off is that the step is interactive — fine for one
node; an unattended rebuild would use a single-use, short-lived auth key.

Then, in the Tailscale admin console: *Machines →* `<node-name>` *→ Disable key
expiry*. A device must re-authenticate every 180 days by default; on a server
that silently drops it from the tailnet, and the cluster's API with it.

On the operator's machine: install the Tailscale app
(`brew install --cask tailscale-app`, which asks for the macOS admin password)
and sign in to the same tailnet.

**Verify:**

```bash
tailscale status                   # both machines listed
tailscale ping <node-name>     # "via <public-ip>:41641" is direct; "via DERP(...)" is relayed
ssh <admin-user>@<node-name> hostname
tailscale status --json | jq '.Peer[] | select(.HostName=="<node-name>") | {Tags, KeyExpiry}'
```

The first pings may go through a DERP relay until NAT traversal finds a direct
path; on 2026-10-12 it became direct within seconds. A path that stays on DERP
works, only slower.

The last command must print `"tag:lagom-node"` (after the ACL step below) and
`"KeyExpiry": null`, which is what *Disable key expiry* sets.

The node is `<node-name>.<tailnet>.ts.net`, `<node-tailnet-ip>`; `tailscale
status` on either machine prints both.

### Install k3s (M1)

Configuration first, as files, so the install is declarative and re-runnable;
then the official installer with a pinned version. On the node:

```bash
IP=$(tailscale ip -4)
sudo install -d -m 0755 /etc/rancher/k3s
sudo tee /etc/rancher/k3s/config.yaml >/dev/null <<EOF
node-name: <node-name>
tls-san:
  - <node-name>.<tailnet>.ts.net
  - $IP
secrets-encryption: true
disable:
  - traefik
  - servicelb
  - local-storage
  - metrics-server
EOF
sudo chmod 0600 /etc/rancher/k3s/config.yaml
sudo install -d -m 0755 /etc/systemd/system/k3s.service.d
printf '%s\n' '[Service]' 'Environment=GOMEMLIMIT=900MiB' \
  | sudo tee /etc/systemd/system/k3s.service.d/memory.conf
curl -sfL https://get.k3s.io -o /tmp/k3s-install.sh
sudo INSTALL_K3S_VERSION="v1.36.5+k3s1" sh /tmp/k3s-install.sh
```

The heredoc is unquoted so the shell fills in `$IP`, the node's tailnet
address; nothing else in it starts with `$`.

**Why it works.** The installer creates the `k3s` systemd unit; on every start
k3s reads `config.yaml`, where each key is the long form of a command-line flag.

- `tls-san` adds names to the API server's certificate. `kubectl` checks that
  the name it connects to is in the certificate, so the tailnet name must be
  listed or every connection over Tailscale fails TLS verification.
- `disable` keeps k3s from installing those packaged components; a component
  disabled on a running cluster is uninstalled
  ([ADR-0021](adr/0021-k3s-packaged-components-under-git.md), which also says
  in what order the switch was made).
- `secrets-encryption` encrypts Secret objects in the datastore (SQLite) with a
  key generated on the node. It protects a copy of the datastore — a stolen
  disk image or backup. It does not protect against root on the node, which
  holds the key.
- The version is the `stable` channel on 2026-10-12. Upgrading is a deliberate
  change, preceded by a staging rebuild ([ADR-0007](adr/0007-three-environments.md)).

**Memory limit for the Go runtime** — the `memory.conf` above. Without it,
`k3s-server` grew to 1.2 GB holding memory it did not use
([ADR-0011](adr/0011-memory-viability-on-4gb.md)). A systemd drop-in survives
reinstalls of k3s, unlike the installer's environment file, which the
installer rewrites. Written before the installer runs, it applies from k3s's
first start (exercised 2026-10-28); on a node where k3s already runs, add it
and run `sudo systemctl daemon-reload && sudo systemctl restart k3s`.

The figure is 900MiB on the 8 GB node too. `GOMEMLIMIT` bounds k3s's own heap,
which grows with the objects in the cluster, not with the node's RAM; the
cluster moved unchanged, so the figure that stopped GC thrash on 4 GB still
fits. Measured on 2026-10-28, two hours after k3s started: 115 garbage
collections since start, no thrash
([ADR-0024](adr/0024-ci-ceiling-on-the-8-gb-node.md)); re-checked with the
three-day measurement, by the check below.

**Check the limit still has headroom** whenever the cluster gains a component.
If collections run several times per second and the node's CPU is near 100%
while pods use little, the runtime has hit the limit — raise it and record
the measurement ([ADR-0011](adr/0011-memory-viability-on-4gb.md) notes):

```bash
kubectl get --raw /metrics | grep -E '^go_(memstats_sys_bytes|gc_gomemlimit_bytes|goroutines|gc_duration_seconds_count) '
kubectl get --raw /api/v1/nodes/<node-name>/proxy/stats/summary   # CPU of "kubelet" (k3s) vs "pods"
```

Restarting k3s does not stop running containers (`KillMode=process`); only the
API is unavailable for a few seconds.

Traefik and servicelb are not installed, and local-path and metrics-server are
installed by Argo CD instead of k3s ([ADR-0021](adr/0021-k3s-packaged-components-under-git.md)):
the `disable:` list in `config.yaml` above. metrics-server is what `kubectl top`
needs to measure the budget in §11. **On a fresh install the cluster has no
storage class until Argo CD syncs `local-path`**; the Postgres `Cluster`s wait
for it (their volumes bind on first use). The API (6443) and kubelet (10250)
listen on all interfaces. **The Hetzner firewall is what keeps them
private** — which is why the check below probes from outside.

**Verify:**

```bash
sudo k3s kubectl get nodes        # <node-name>   Ready
sudo k3s secrets-encrypt status   # Encryption Status: Enabled
sudo k3s kubectl get --raw /metrics | grep '^go_gc_gomemlimit_bytes'   # 9.437184e+08
# from a machine outside the tailnet path, against the public IP:
for p in 22 80 443 6443 10250; do nc -z -G 5 -w 5 <public-ip> $p && echo "$p OPEN" || echo "$p closed"; done
```

Expected: only `22 OPEN` while the firewall still admits SSH.

### Tailscale ACL and zero inbound ports (M1)

The tailnet's default policy lets every device reach every other. The policy
below, applied in the admin console (*Access controls*), replaces it:

```jsonc
{
  "groups": {
    "group:operators": ["<operator-tailscale-login>"],
  },
  "tagOwners": {
    "tag:lagom-node": ["group:operators"],
  },
  "grants": [
    // Operators reach the node: SSH (break-glass) and the Kubernetes API only.
    {"src": ["group:operators"], "dst": ["tag:lagom-node"], "ip": ["tcp:22", "tcp:6443"]},
    // Each person's own devices keep reaching each other.
    {"src": ["autogroup:member"], "dst": ["autogroup:self"], "ip": ["*"]},
  ],
  "tests": [
    {"src": "<operator-tailscale-login>", "accept": ["tag:lagom-node:22", "tag:lagom-node:6443"], "deny": ["tag:lagom-node:10250"]},
    {"src": "tag:lagom-node", "deny": ["<operator-tailscale-login>:22"]},
  ],
}
```

Then *Machines →* `<node-name>` *→ Edit ACL tags →* `tag:lagom-node`.

**Why it works.** A tagged machine belongs to its tag, not to a person, so rules
name roles — operators reach Lagom nodes — instead of people. Anything not
granted is denied, in both directions: operators get SSH and the API and nothing
else (not even the kubelet), and the node can open no connection to anyone's
device, so a compromised node cannot reach the operator's machine. `tests` are
assertions the console checks on every save; a policy that breaks them is
rejected.

**Then close the public firewall.** With the tailnet path verified, the inbound
rule for port 22 is removed from the Hetzner firewall. The firewall itself stays
attached with **no inbound rules, which denies all inbound traffic** — do not
delete or detach it: it is the only thing keeping the API (6443), the kubelet
(10250), and anything a future LoadBalancer Service publishes off the internet,
since k3s listens on every interface. (Until 2026-10-27 that included Traefik
on 80 and 443; [ADR-0021](adr/0021-k3s-packaged-components-under-git.md).) Outbound is unrestricted. Tailscale still connects directly, because
the firewall is stateful and NAT traversal starts from outbound packets.

**Break-glass.** If Tailscale fails on the node, re-add an inbound rule for port
22 from the operator's current IP in the Hetzner Console and SSH to the public
address; remove it afterwards. The Hetzner web console is no way in: the user
has no password (`lock_passwd`), so a console login cannot succeed. The last
resort is Hetzner's rescue system, which boots the node from a separate image.

**Verify** — from outside the tailnet, then through it:

```bash
for p in 22 80 443 6443 10250; do nc -z -G 5 -w 5 <public-ipv4> $p && echo "$p OPEN" || echo "$p closed"; done
for p in 22 80 443 6443 10250; do nc -6 -z -G 5 -w 5 <public-ipv6> $p && echo "$p OPEN" || echo "$p closed"; done
nc -z -G 5 -w 5 1.1.1.1 443                  # control: proves the probe can see an open port
for p in 22 6443 10250; do nc -z -G 5 -w 5 <node-name> $p && echo "$p OPEN" || echo "$p closed"; done
```

Expected: every public port closed while the control succeeds; over the tailnet
22 and 6443 open, 10250 closed. On 2026-10-12 a listener on the operator's
tailnet address was also probed from the node: refused, with a local control
connection to the same listener succeeding.

### Operator kubeconfig (M1)

Fetched from the node, with the server address and every `default` name
replaced by the node's, then merged into `~/.kube/config` so the contexts of
other clusters stay. kubectl merges the files listed in `KUBECONFIG`, and
`config view --flatten` writes the result as one file with the certificates
inline:

```bash
umask 077 && mkdir -p ~/.kube && touch ~/.kube/config
ssh <admin-user>@<node-name> 'sudo cat /etc/rancher/k3s/k3s.yaml' \
  | sed -e 's#https://127.0.0.1:6443#https://<node-name>.<tailnet>.ts.net:6443#' \
        -e 's#: default$#: <node-name>#' > ~/.kube/<node-name>.yaml
KUBECONFIG=~/.kube/config:~/.kube/<node-name>.yaml kubectl config view --flatten > ~/.kube/config.merged \
  && mv ~/.kube/config.merged ~/.kube/config && rm ~/.kube/<node-name>.yaml
kubectl config get-contexts
kubectl --context <node-name> get nodes
```

The merge keeps the current context, so on a machine that already knew
another cluster, `kubectl` without `--context` still talks to that one. While
two clusters are in the file, **name the context on every command**:
`--context <node-name>` for `kubectl` and `kubeseal`, `--kube-context
<node-name>` for `helm`. The commands elsewhere in this runbook that carry no
context assume the current one is the right cluster: add the flag to them, or
switch first with `kubectl config use-context <node-name>`.

This file is the **cluster-admin credential** — a client certificate with every
right in the cluster. It never goes to Git or chat, `umask 077` keeps it
readable only by its owner, and it is not shared: per-developer RBAC replaces it
for anyone else (M7).

### Install Argo CD (M1)

Argo CD is installed once by hand, from the operator's machine over the
tailnet; after the handover below it manages itself
([ADR-0009](adr/0009-argocd-bootstrap-and-self-management.md)).

```bash
helm repo add argo https://argoproj.github.io/argo-helm && helm repo update argo
helm template argocd argo/argo-cd --version 10.10.3 -n argocd \
  -f platform/infra/argocd/values.yaml > /tmp/argocd.yaml   # inspect before installing
helm install argocd argo/argo-cd --version 10.10.3 -n argocd --create-namespace \
  -f platform/infra/argocd/values.yaml --wait
kubectl -n argocd get pods
```

Expected: `argocd-application-controller-0`, `argocd-repo-server`,
`argocd-server`, and `argocd-redis` Running; `argocd-redis-secret-init`
Completed. No Dex, notifications, or ApplicationSet pods.

**Repository access — none needed.** The repository is public, and every
Application names it by its HTTPS URL, so Argo CD clones it anonymously, the
way any reader can. There is no repository Secret in the cluster and no key at
GitHub to create, rotate, or lose on a rebuild
([ADR-0017](adr/0017-public-repository-from-a-snapshot.md)). The trade-off:
anonymous reads are subject to GitHub's unauthenticated limits, which a poll
every few minutes stays far below.

**Break-glass.** If a change to the values file breaks Argo CD, it cannot apply
its own fix. Revert the commit, then re-apply the chart by hand with the
`helm upgrade` form of the install command above (`helm upgrade argocd ...`
with the same flags); Argo CD resumes from `main`.

### Hand over to Argo CD (M1)

Once `platform/infra/` is on `main`, apply the root Application — the last
command run by hand against the cluster:

```bash
kubectl apply -f platform/infra/apps/root.yaml
kubectl -n argocd get applications
```

Expected within a few minutes: every Application in `platform/infra/apps/`
`Synced` and `Healthy`. `root` syncing is also the proof that Argo CD can read
the repository.

**On an empty cluster the Applications race.** `root` creates them all at
once, with no sync order, so `postgres-prod` and `postgres-staging` can try to
create a `Cluster` and `SealedSecret`s before CloudNativePG and Sealed Secrets
have installed those types. That sync fails and Argo CD retries it: its
automated sync retries five times with backoff by default (Argo CD v3.5.5 —
the retry is not set in our manifests). On 2026-10-28 `postgres-prod` failed
twice and succeeded on the third try, 32 s after `root` was applied; all nine
Applications were `Synced/Healthy`, with both Postgres `Cluster`s ready, 65 s
after it. A sync still failed after five tries stays failed until the next
commit; sync it once by hand
(`argocd app sync <app> --core --kube-context <node-name>`).

The first sync of `argocd` adopts the objects that `helm install` created, and
takes longer than the others. When a change restarts the application controller
itself, the Application can show `OutOfSync` until the restarted controller
re-reads it. Check whether a difference is real before acting:

```bash
kubectl config set-context --current --namespace=argocd
argocd app diff argocd --core      # no output means no difference
kubectl config set-context --current --namespace=default
```

`argocd` is the CLI (`brew install argocd`). `--core` makes it talk to the
cluster through the kubeconfig instead of logging in to the Argo CD API.

### Deploy (M1)

**How a commit reaches the cluster:** pull request → merge to `main` → Argo CD
notices the new commit on its next poll → applies the difference → the workload
picks it up. Nothing is run against the cluster by hand.

Argo CD **polls Git** every 120 s plus up to 60 s of jitter (the chart defaults
for `timeout.reconciliation`), so a merge lands within about three minutes. It
**watches the cluster** continuously, so a manual change there is reverted
almost at once (`selfHeal`).

Measured on 2026-10-13:

| Test | Result |
|---|---|
| Merge a one-line change to `platform/infra/hello/configmap.yaml` | merged 13:34:59, applied by Argo CD 13:36:05, served by nginx ~20 s later; the pod did not restart |
| `kubectl -n hello scale deployment hello --replicas=2` by hand | reverted to 1 replica by Argo CD after 2 s |

**Check state:**

```bash
kubectl -n argocd get applications                       # Synced / Healthy per Application
kubectl -n argocd get application hello -o jsonpath='{.status.sync.revision}'   # commit applied
```

A manual change to anything under Argo CD's management is not a deployment: it
is undone on the next pass. To change the cluster, change `main`.

### Sealed Secrets (M1)

Installed by Argo CD from `platform/infra/apps/sealed-secrets.yaml`
([ADR-0010](adr/0010-sealed-secrets.md)). The operator needs `kubeseal`
(`brew install kubeseal`).

**Seal a secret.** The value is read without echo, so it stays out of the
terminal and the shell history; the file name ends in `-sealed.yaml`, the only
secret-like name `.gitignore` lets through:

```bash
read -rs VALUE
kubectl create secret generic <name> -n <namespace> --from-literal=<key>="$VALUE" \
  --dry-run=client -o yaml | kubeseal --format yaml > platform/infra/<component>/<name>-sealed.yaml
unset VALUE
```

The sealed file is bound to `<name>` and `<namespace>`: renaming it or applying
it elsewhere makes it undecryptable, by design.

**Back up the sealing key — the operator, once after install and after every
rotation.** Without this file a rebuilt cluster cannot decrypt anything in Git:

```bash
kubectl -n kube-system get secret -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > sealed-secrets-key.yaml
# add the file to 1Password as a Document, then delete the local copy
rm sealed-secrets-key.yaml
```

**Restore on a rebuild** — after Argo CD is installed and before the root
Application, so the controller finds the key when Argo CD first starts it and
never generates one of its own. Save the Document from 1Password to the home
folder (not a folder iCloud syncs), apply it, delete it:

```bash
kubectl --context <node-name> apply --dry-run=server -f ~/sealed-secrets-key.yaml   # "created (server dry run)"
kubectl --context <node-name> apply -f ~/sealed-secrets-key.yaml
rm ~/sealed-secrets-key.yaml
kubectl --context <node-name> -n kube-system get secret -l sealedsecrets.bitnami.com/sealed-secrets-key   # exactly one
```

The exported file still carries its old cluster's `resourceVersion` and `uid`;
on 2026-10-28 the API server accepted it as it is. If it ever refuses
(`resourceVersion should not be set`), strip those lines first:
`sed -E '/^[[:space:]]+(resourceVersion|uid|creationTimestamp):/d'`. Only if
the controller was already running when the key arrived, restart it so it
reloads its keys:
`kubectl --context <node-name> -n kube-system delete pod -l app.kubernetes.io/name=sealed-secrets`.

**Verify** once Argo CD has synced `sealed-secrets`: every `SealedSecret` is
`SYNCED True`, and the controller's certificate is the one the backup was
taken from. With the old cluster still up, compare the two certificates;
without it, `SYNCED True` on every `SealedSecret` is the evidence, since no
other key can decrypt them:

```bash
kubectl --context <node-name> get sealedsecrets -A
for c in <old-node-name> <node-name>; do kubeseal --context $c --fetch-cert | openssl x509 -noout -fingerprint -sha256; done
```

Exercised 2026-10-28: one key Secret, five `SealedSecret`s `SYNCED True`, and
the same fingerprint on both nodes.

### Postgres (M2)

Prod runs as the CloudNativePG `Cluster` `postgres` in namespace `prod`
([ADR-0012](adr/0012-cloudnative-pg.md)), created by Argo CD from
`platform/infra/postgres-prod/`. Services: `postgres-rw` (the primary, for
writes), `postgres-ro` and `postgres-r` (reads), all ClusterIP.

**Check it is healthy:**

```bash
kubectl -n argocd get application postgres-prod      # Synced / Healthy
kubectl -n prod get cluster postgres                 # "Cluster in healthy state"
```

**Run SQL as administrator.** There is no superuser password
(`enableSuperuserAccess: false`); the local socket inside the Pod is the way in:

```bash
kubectl -n prod exec -it postgres-1 -c postgres -- psql
```

**Credentials** are generated by the operator in the Secret `postgres-app`,
never in Git. List secrets by name only — `kubectl get secret -o yaml` prints
the values, base64-encoded rather than encrypted:

```bash
kubectl -n prod get secrets -o name
```

Connecting to prod from the operator's machine (port-forward over the tailnet)
is *not yet exercised*; it is written here when dlt and dbt first connect.

#### Staging

Staging runs the same way in namespace `staging`, from
`platform/infra/postgres-staging/`: a `Cluster` `postgres` with the same
settings as prod's, the managed role `lagom_dev` and the `Database` `lagom-dev`
([ADR-0014](adr/0014-develop-against-staging.md)). Prod's NetworkPolicy
(`platform/infra/postgres-prod/networkpolicy.yaml`) drops traffic from staging.

Exercised on 2026-10-17, after the first deploy.

**Check it is healthy:**

```bash
kubectl -n argocd get application postgres-staging  # Synced / Healthy
kubectl -n staging get cluster postgres             # "Cluster in healthy state"
kubectl -n staging get database lagom-dev           # APPLIED true
kubectl -n staging describe resourcequota staging   # Used against Hard
```

**Check that staging cannot reach prod** — `BLOCKED` is the pass; run the same
command with `-n prod` as the control, which must print `REACHED`. The image is
the one the `hello` app already keeps on the node:

```bash
kubectl -n staging run nettest --rm -i --quiet --restart=Never \
  --image=nginxinc/nginx-unprivileged:1.30.5-alpine -- \
  sh -c 'nc -z -w 4 postgres-rw.prod.svc.cluster.local 5432 && echo REACHED || echo BLOCKED'
```

Result on 2026-10-17: staging → prod `BLOCKED`; prod → prod and staging →
staging `REACHED`.

**Connect as the developer.** The password is in the Secret
`lagom-dev-credentials`, unsealed by the Sealed Secrets controller. Put it in an
environment variable of the current shell, so it is never typed or printed, and
forward the port:

```bash
export PGPASSWORD=$(kubectl -n staging get secret lagom-dev-credentials \
  -o jsonpath='{.data.password}' | base64 -d)
kubectl -n staging port-forward svc/postgres-rw 15432:5432 &
```

dlt and dbt read these as their own connection settings. For an ad-hoc query
without installing `psql`, a throwaway `uv` environment is enough:

```bash
uv run --no-project --with 'psycopg[binary]' python -c \
  "import psycopg; print(psycopg.connect(host='127.0.0.1', port=15432, user='lagom_dev', dbname='lagom_dev', sslmode='disable').execute('select current_user, current_database()').fetchone())"
```

**Use `sslmode=disable` over the port-forward.** With Postgres TLS, `kubectl
port-forward` exits after the first session closes ("connection reset by
peer… lost connection to pod"), so the next connection fails — found on
2026-10-17 on the first dlt load, reproduced with psycopg2: four sessions
without TLS kept the tunnel up, the second session with TLS killed it. The
hop is still encrypted end to end except on loopback: WireGuard (Tailscale)
to the node, TLS to the API server and from it to the kubelet; the password
travels as a SCRAM exchange, never in clear. In-cluster clients keep TLS.

The trade-off: the command line is recorded in shell history, but it holds the
Secret's name, not the password; the password lives in the shell's environment
until the shell exits (`unset PGPASSWORD` sooner), where any process the shell
starts can read it. A `~/.pgpass` file avoids the environment but leaves the
password on disk.

Verified on 2026-10-17: `lagom_dev` connects to `lagom_dev` over TLS; connecting
to `lagom` is refused before authentication, and Postgres logs
`pg_hba.conf rejects connection for host "127.0.0.1", user "lagom_dev",
database "lagom"` for both TLS and plain connections.

#### Staging: the pipeline CronJob

Exercised on 2026-10-18. The CronJob `usgs-pipeline`
([`cronjob-usgs.yaml`](../platform/infra/postgres-staging/cronjob-usgs.yaml))
runs every 30 minutes. It needs the Secret `ghcr-pull` (a sealed
`dockerconfigjson`, [ADR-0015](adr/0015-images-on-ghcr.md)) in the namespace;
without it the Pod stays in `ImagePullBackOff`. The first run, on demand: both
private images pulled by digest, dlt loaded 9,929 events, dbt `PASS=32`, in
37 s; staging's `lagom` reconciled bronze 9,929 → silver 9,929 → gold 9,710 →
daily aggregate 9,710. Prod runs the same CronJob, promoted with the same
digests ([`cronjob-usgs.yaml`](../platform/infra/postgres-prod/cronjob-usgs.yaml)).

**Seal a pull credential** — a classic token with only `read:packages`, one per
namespace. Paste the token **when the command stops and waits**, never into the
command line, which the shell keeps in its history; the first line prints only
its length (a classic token is 40, and seals to 956 characters):

```bash
read -rs TOKEN && echo "token length: ${#TOKEN}" && kubectl create secret docker-registry ghcr-pull -n <namespace> \
  --docker-server=ghcr.io --docker-username=FilipeFantini --docker-password="$TOKEN" --dry-run=client -o yaml \
  | kubeseal --format yaml > platform/infra/postgres-<namespace>/ghcr-pull-sealed.yaml; unset TOKEN
grep -a -c 'ghp_' ~/.zsh_history ~/.zsh_sessions/* 2>/dev/null   # all 0: the token is in no history
```

If a token ever lands in the history, revoke it in GitHub's settings, delete
the lines (`sed -i '' '/ghp_/d'` on each file, with every Terminal window
closed first, since an open shell rewrites its history on exit), and seal a new
one — what happened on 2026-10-18.

**Run it on demand** (a Job made from the CronJob's template; `date +%s` makes
the name unique):

```bash
kubectl -n staging create job --from=cronjob/usgs-pipeline usgs-manual-$(date +%s)
kubectl -n staging get pods -w       # Init:0/2 while dlt runs, Init:1/2 while dbt runs, then Running, Completed
```

If the scheduled run is active, the quota refuses the second Pod (room for one
at a time); wait for it to finish.

**Read the logs.** The load and the transform are the two init containers, in
that order; the heartbeat is the only regular container. Replace the Pod name
from `get pods`:

```bash
kubectl -n staging logs <pod> -c ingest       # dlt: "loaded N rows into usgs_events"
kubectl -n staging logs <pod> -c transform    # dbt build: models and tests
kubectl -n staging logs <pod> -c heartbeat    # "heartbeat sent: HTTP 200"
kubectl -n staging describe pod <pod>         # exit codes, OOMKilled, events
```

If `ingest` fails, `transform` never starts and the Pod shows `Init:Error`;
if either fails, `heartbeat` never starts. Both are the intended stop, not a
second failure.

**Check the row counts** through the Pod's local socket (no password, no
port-forward). The socket session is the administrator's, as in the section
above; the query only reads, and `-d lagom` selects staging's database:

```bash
kubectl -n staging exec postgres-1 -c postgres -- psql -d lagom -c \
  "select (select count(*) from bronze.usgs_events) as bronze,
          (select count(*) from silver.stg_usgs__events) as silver,
          (select count(*) from gold.fct_earthquakes) as gold,
          (select max(properties__updated) from bronze.usgs_events) as newest_updated"
```

Bronze holds every revision, silver one row per event, gold only earthquakes,
so `bronze >= silver >= gold`. The exact relation names are those of the dbt
models; correct this command on the first run if one differs. Memory use of a
run, to replace the starting 256 MiB request, is read with `kubectl top pod`
while it runs.

Pod to Service connections keep TLS (`LAGOM_PG_SSLMODE=require`); only the
port-forward path above uses `sslmode=disable`.

#### Pipeline heartbeat

Each run that loads and builds ends with a ping to its environment's check at
Healthchecks.io; a missing ping is the alarm
([ADR-0018](adr/0018-pipeline-heartbeat.md)). The account and the checks are
made by hand, in its console:

- One check per environment, `lagom-usgs-staging` and `lagom-usgs-prod`.
- Schedule: *Cron*, `*/30 * * * *`, time zone UTC, the CronJob's schedule.
- Grace: 20 minutes, the latest a healthy run can ping (up to 5 minutes late
  to start, up to 15 to finish).
- Integration: e-mail to the operator.

**Seal the ping URL**, one per namespace. The URL is a secret — whoever has it
can report a success — so it is pasted when the command waits, never typed on
the command line:

```bash
read -rs HC_URL && echo "url length: ${#HC_URL}" && kubectl create secret generic pipeline-heartbeat -n <namespace> \
  --from-literal=url="$HC_URL" --dry-run=client -o yaml \
  | kubeseal --format yaml > platform/infra/postgres-<namespace>/pipeline-heartbeat-sealed.yaml; unset HC_URL
```

A Healthchecks.io ping URL is `https://hc-ping.com/` (20 characters) plus a
36-character UUID, 56 in all.

**Verify** after the change reaches the namespace: the next run's `heartbeat`
log says `heartbeat sent: HTTP 200`, and the check turns *up* in the console.
The container's 32 MiB request and 64 MiB limit are starting figures: read its
memory with `kubectl top pod --containers` during a run and correct them. An
`OOMKilled` heartbeat fails the Job, and after the retry the check goes quiet:
an alarm for a run that worked.

**When the e-mail arrives**, the check went quiet: read the Jobs and the logs
above. No Job at all means the CronJob is not scheduling or the node is down;
`Init:Error` means the load or the build failed; a failed `heartbeat` with
three `heartbeat attempt … failed` lines means the run worked and the ping did
not.

### Backup and restore (M3)

Each environment's Postgres is backed up to its own R2 bucket by the Barman
Cloud plugin ([ADR-0025](adr/0025-postgres-backup-barman-cloud-to-r2.md)):

| Environment | Bucket | Retention |
|---|---|---|
| staging | `lagom-staging-backups` | 7 days |
| prod | `lagom-prod-backups` | 30 days |

Two kinds of copy land there:

- **WAL**, continuously. Each write-ahead log segment is uploaded as soon as
  Postgres closes it, which happens at the latest every 5 minutes.
- **A base backup** every day at 03:00 UTC.

A restore replays WAL on top of a base backup. It can reach any moment up to
the last archived segment, so at most about **5 minutes of writes** are lost
(the RPO).

**Set it up for an environment** (exercised in staging, 2026-10-28):

1. In the Cloudflare console, R2: create the bucket `lagom-<env>-backups`
   with *Location hint: Western Europe*. Then create an API token with
   *Object Read & Write* on that bucket only, TTL *Forever*. Save the
   access key, the secret and the S3 endpoint (no bucket in it) in 1Password
   as `R2 Storage lagom-<env>-backups`.
2. Seal it. Each prompt waits for a value pasted from 1Password, and nothing
   is echoed. Expected lengths are 32, 64 and 65:

   ```bash
   printf 'Access Key ID: ' && read -rs KEY_ID && echo && printf 'Secret Access Key: ' && read -rs SECRET && echo && printf 'S3 endpoint: ' && read -rs ENDPOINT && echo && echo "lengths: ${#KEY_ID} ${#SECRET} ${#ENDPOINT}" && kubectl --context <node-name> create secret generic r2-backups -n <env> --from-literal=ACCESS_KEY_ID="$KEY_ID" --from-literal=ACCESS_SECRET_KEY="$SECRET" --from-literal=ENDPOINT="$ENDPOINT" --dry-run=client -o yaml | kubeseal --context <node-name> --format yaml > platform/infra/postgres-<env>/r2-backups-sealed.yaml; unset KEY_ID SECRET ENDPOINT
   ```

3. Add the `ObjectStore`, the `ScheduledBackup` and `spec.plugins` to the
   environment's directory, then merge. On a running Cluster the operator
   restarts the Postgres Pod once to add the sidecar. That took a few seconds
   in staging.

**Check it works:**

```bash
kubectl --context <node-name> -n <env> get cluster postgres -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.message}{"\n"}{end}'
kubectl --context <node-name> -n <env> get backups
kubectl --context <node-name> -n <env> logs postgres-1 -c plugin-barman-cloud --since=10m | grep -E 'Archived WAL file|Backup completed'
```

`ContinuousArchiving=True` and `LastBackupSucceeded=True` are the pass. If
archiving fails, Postgres keeps the WAL it could not ship on its volume, so
the volume grows: read the sidecar's log.

**The first backup after enabling can fail.** The `ScheduledBackup` takes one
backup at once (`immediate: true`). On a Cluster that is still restarting to
add the plugin, that backup fails with `cannot proceed with the backup as the
cluster has no plugin configured`. This happened in staging on 2026-10-28.
Take one by hand once the Pod is back:

```bash
N=manual-$(date -u +%Y%m%d%H%M); kubectl --context <node-name> -n <env> apply -f - <<YAML && kubectl --context <node-name> -n <env> wait backup/$N --for=jsonpath='{.status.phase}'=completed --timeout=600s
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: $N
spec:
  cluster:
    name: postgres
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
YAML
```

The heredoc is unquoted so the shell fills in `$N`. Nothing else in it
starts with `$`.

**Test a restore** into a temporary Cluster in the same namespace. It reads
the bucket and archives nothing of its own. Its memory request is small so it
fits staging's quota. Then compare the row counts and delete it:

```bash
kubectl --context <node-name> -n <env> apply -f - <<'YAML' && kubectl --context <node-name> -n <env> wait cluster/restore-test --for=condition=Ready --timeout=900s
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: restore-test
spec:
  instances: 1
  imageName: <the imageName of the environment's Cluster>
  storage: {size: 5Gi, storageClass: local-path}
  resources:
    requests: {cpu: 10m, memory: 128Mi}
    limits: {memory: 512Mi}
  bootstrap:
    recovery: {source: origin, database: lagom, owner: lagom}
  externalClusters:
    - name: origin
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters: {barmanObjectName: r2-backups, serverName: postgres}
YAML
for c in postgres restore-test; do echo "$c | $(kubectl --context <node-name> -n <env> exec $c-1 -c postgres -- psql -d lagom -At -F' | ' -c "select (select count(*) from bronze.usgs_events), (select count(*) from silver.stg_usgs__events), (select count(*) from gold.fct_earthquakes)")"; done
kubectl --context <node-name> -n <env> delete cluster restore-test
```

Result in staging on 2026-10-28: ready 68 s after creation. The copy held
every row up to the last archived WAL (14:28 UTC). The 9 rows a pipeline run
wrote at 14:30, in a segment not yet closed, were missing, as the RPO above
predicts. Deleting the Cluster deletes its volume: local-path released it
within two minutes.

**Retention** is enforced by the sidecar every 30 minutes. Check it after the
first week. An expired backup must be gone from `kubectl get backups` and from
the bucket, with no `BadDigest` or `DeleteObjects` error in the sidecar's log:

```bash
kubectl --context <node-name> -n <env> logs postgres-1 -c plugin-barman-cloud --since=24h | grep -iE 'retention|delete|error'
```

**Memory measured** on 2026-10-28 is in §11: the sidecar used 18 Mi during a
base backup.

### Disaster recovery

Used when the node is lost, or when the platform moves to a new node. The
path exercised is a **rebuild from Git plus a re-load from USGS**, on
2026-10-28, moving from `lagom-shared-01` to `lagom-shared-02`, with the old
node still up. Since the same day, Postgres is also backed up to R2, and a
restore into a new Cluster is tested ([Backup and restore](#backup-and-restore-m3)).
A rebuild that bootstraps each Cluster from its bucket would also keep the
event revisions a re-load loses, but it has not been run. Until it has, the
re-load below is the proven path.

**What survives the node, and where.** Everything the cluster runs is in Git.
The sealing key and the SSH key are in 1Password. The Healthchecks.io checks,
the GHCR images and the Tailscale policy live with their services. What is
lost: Postgres's data (the re-load rebuilds the last 30 days of events, see
below), dlt's cursor (rebuilt by the first run), and staging's `lagom_dev`
(disposable by design). The Postgres passwords change: CloudNativePG
generates new ones in `postgres-app`, and every consumer reads that Secret, so
nothing has to be updated.

**Procedure** — the sections above, in this order, on a node named with the
next index:

1. [Provision the node](#provision-the-node-m0). An ARM type: the images are
   built for arm64 only.
2. [Join the tailnet](#join-the-tailnet-m1), tag it `tag:lagom-node` and
   disable key expiry. The [ACL](#tailscale-acl-and-zero-inbound-ports-m1)
   already grants the tag, so it is not edited.
3. [Install k3s](#install-k3s-m1), including the public-port check.
4. [Add the kubeconfig context](#operator-kubeconfig-m1).
5. [Install Argo CD](#install-argo-cd-m1).
6. [Restore the sealing key](#sealed-secrets-m1) — before step 7.
7. [Apply the root Application](#hand-over-to-argo-cd-m1) and wait for every
   Application to be `Synced/Healthy` and both Postgres `Cluster`s ready.
8. Run the pipeline [on demand](#staging-the-pipeline-cronjob), staging first,
   then prod (`kubectl --context <node-name> -n <namespace> create job
   --from=cronjob/usgs-pipeline usgs-manual-$(date +%s)`). Each Pod must show
   `ingest`, `transform` and `heartbeat` with exit 0, `Done. PASS=… ERROR=0`
   in `transform`, and `heartbeat sent: HTTP 200` in `heartbeat`. With no
   cursor, the first run is the re-load.
9. Check the row counts (the query in
   [the CronJob section](#staging-the-pipeline-cronjob)): `bronze >= silver >=
   gold`. dbt's `reconcile_*` tests already assert the relations between
   layers in step 8.

**While two clusters run at once** (a move, or a drill with the old node up):

- **Both reconcile the same `main`.** A merge reaches both. Merge nothing to
  `platform/infra/` that is meant for one node only.
- **Both run the CronJobs and ping the same Healthchecks.io checks**, because
  the sealed URLs decrypt with the same key on both. A check that stays *up*
  proves nothing about the new node: the old one's pings would hide its
  failures. Judge the new node by its `heartbeat` log, and power the old one
  off as soon as the new one passes (the *When* paragraph of
  [the checklist below](#retire-the-old-node)).
- Both call the USGS API. Four requests every 30 minutes is far below any limit.

**Measured on 2026-10-28** (timestamps from the drill's log, UTC):

| Step | Start | Took | Notes |
|---|---|---|---|
| 1. Tailnet, tag, key expiry | — | not timed | done before the drill; verified with `tailscale status --json` |
| 2. k3s (config, `GOMEMLIMIT`, install, checks) | 11:53:44 | 2 min 53 s | the installer itself took 26 s; the rest is verification and the port probes |
| 3. kubeconfig context | 11:56:47 | 2 s | |
| 4. Argo CD (`helm install --wait`) | 11:59:16 | 36 s | |
| 5. Sealing key | 12:01:30 | 2 s | the exported Document applied as it is |
| 6. Root Application to all `Synced/Healthy` | 12:01:32 | 65 s | `postgres-prod` retried twice (the race above) |
| 7a. Staging run | 12:10:12 | 49 s | 9,883 rows loaded, `PASS=34`, heartbeat 200 |
| 7b. Prod run | 12:13:45 | 30 s | 9,884 rows loaded, `PASS=34`, heartbeat 200 |

**RTO: 20 min 31 s**, from the first command on the node to prod's first green
run. About 6 minutes of it is the machine working; the rest is the operator
reading results and starting the next step. It **excludes provisioning** (the
server, cloud-init and the tailnet join were done before the drill and not
timed; M0 estimated half an hour), so a rebuild from nothing is about 50
minutes. That figure is an estimate, not a measurement. It also excludes
history older than 30 days, which cannot be re-loaded (below).

**What the re-load brings back.** Compared with the old node, both loaded by
their 12:30 runs:

| | bronze | silver | gold | oldest `updated` in bronze |
|---|---|---|---|---|
| old node, prod (loading since 2026-10-18) | 16,225 | 13,836 | 13,524 | 2026-09-18 |
| new node, prod (first run 12:14) | 9,884 | 9,884 | 9,633 | 2026-09-28 |

On the new node, bronze equals silver: a first load holds one revision per
event, and later revisions accumulate from the next runs. Within the node,
`bronze >= silver >= gold` holds, and dbt's `reconcile_*` tests passed in
every run (`PASS=34`), including the scheduled 12:30 runs. The new node has
3,952 events fewer in prod: those with an origin older than 30 days, which
the USGS API does not return without `starttime` (the API's own `count`:
9,474 events updated since 2026-10-01 without it, 12,318 with
`starttime=2026-08-01`). **The operator accepted this limit on 2026-10-28**
([ADR-0019](adr/0019-postgres-backup-deferred.md) notes): recovery brings
back the last 30 days of events. A comparison of event ids between the two
nodes over a shared window was not run.

**Gaps the drill found, and what changed:**

- The kubeconfig command overwrote `~/.kube/config`. It now merges, and
  every command while two clusters are known names its context.
- `GOMEMLIMIT` was added after the install, with a restart. The drop-in is now
  written before the installer runs, so k3s starts with it.
- The runbook hard-coded `lagom-shared-01`. It now uses `<node-name>`.
- The `GOMEMLIMIT` check ran `kubectl` before the kubeconfig existed. It now
  runs on the node (`sudo k3s kubectl`).
- The expected Applications after the hand-over listed three of nine, and the
  race on an empty cluster was undocumented. Both are now in
  [Hand over to Argo CD](#hand-over-to-argo-cd-m1).
- The sealing-key restore had never run. It worked as written. The section
  now says when to run it, how to verify it, and what to do if the API refuses
  the exported fields.
- The re-load reaches 30 days back at most, and normal runs never load a
  revision published after an event is 30 days old. This is a limit of the
  USGS API's default, not of the runbook, and the operator accepted it
  ([`services/usgs/README.md`](../services/usgs/README.md)).

#### Retire the old node

**When:** first power it off, as soon as the new node's staging and prod runs
pass. In the Hetzner Console choose *Power off*, not *Delete*: it is
reversible, and it stops the old node's CronJobs and heartbeats. Then wait
**24 hours**, in which both Healthchecks.io checks must stay *up* (48 pings
each, all from the new node). Delete only after that.

**What to remove**, in this order:

1. **Hetzner — the server.** Turn off its delete and rebuild protection, then
   delete it, together with its primary IPv4 and IPv6 (Hetzner offers to
   delete them with the server; nothing else uses them).
2. **Hetzner — its firewall.** Open *Firewalls* and check *Resources*: delete
   the firewall only if the old server was its only resource. If the new node
   uses the same firewall, keep it.
3. **Tailscale.** *Machines →* `<old-node-name>` *→ Remove*.
4. **The operator's kubeconfig** — the old cluster's context, cluster and
   credential, then make the new one current:

   ```bash
   kubectl config delete-context <old-node-name>
   kubectl config delete-cluster <old-node-name>
   kubectl config delete-user <old-node-name>
   kubectl config use-context <node-name>
   ```

5. **The operator's `known_hosts`:** `ssh-keygen -R <old-node-name>`.

Nothing in Git needs to change. Only records of the old node's history still
name it.

### Sections to fill as the platform is built

- **Disaster recovery from a backup** — rebuilding the node, then
  bootstrapping each Cluster from its bucket instead of `initdb`. The restore
  itself is exercised in *Backup and restore* above. A full rebuild that
  uses it is not exercised yet.
- **Secret rotation** — how to rotate a source credential and a database
  password. (M3, when a credential is first rotated: the drill rotated
  nothing)
- **On failure** — where to look: Argo CD sync state, Dagster run history, pod
  logs. (M3)

Each section is written when the corresponding milestone is implemented, with
commands that were actually run — never from memory.
