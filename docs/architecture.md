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

**The lakehouse is the destination design, deferred with a trigger.** Object
storage with an open table format for bronze and silver, and DuckDB as the
compute engine, enter when a measured limit appears — see
[ADR-0008](adr/0008-postgres-for-all-layers.md). Until then every layer lives in
Postgres.

Dagster orchestrates from the outside: it triggers jobs and records state,
lineage, and retries. It is not a step in the flow because data does not pass
through it.

## 3. Infrastructure

| Resource | Role |
|---|---|
| Hetzner CAX11 (2 ARM vCPU, 4 GB), `lagom-shared-01` in `nbg1` | control plane and main node; hosts the prod and staging namespaces |
| Raspberry Pi 3B (1 GB) | edge agent node, streaming collector |
| `getlagom.app` domain, registered and served by Cloudflare | public entry via Cloudflare (M4) |

Cost: EUR 7.37/month for the node, as shown in the Hetzner Console on
2026-10-12 ([ADR-0002](adr/0002-single-node-k3s-hetzner.md)). No object storage until the lakehouse
trigger; the prices checked for that moment are in ADR-0008.

**Outside the cluster, principle 3 does not hold yet.** The server, its
firewall, the Tailscale ACL, and the Healthchecks.io checks are created by
hand, following the runbook (§13); the domain's zone at Cloudflare was set up by
hand in its console, and Cloudflare Access does not exist yet (M4). Argo CD
reconciles only what runs inside the cluster. Terraform takes over these
resources by trigger — see [`roadmap.md`](roadmap.md#trigger-table).

### Kubernetes — k3s

k3s is CNCF-certified Kubernetes, not a reduced variant: same API, same
manifests, same `kubectl`. See [ADR-0002](adr/0002-single-node-k3s-hetzner.md).

Three k3s defaults to be aware of, so they are not mistaken for upstream
behaviour:

| Default | Market standard | Our choice |
|---|---|---|
| Traefik as ingress | ingress-nginx | keep Traefik, knowing it is a k3s choice |
| local-path storage | a real CSI driver | fine on a single node; volume is pinned to the node |
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
the lakehouse enters** — see [ADR-0004](adr/0004-table-format.md).

**Rule for this phase, to avoid overengineering:** no catalog, no optimization,
no snapshot maintenance. Write and read by path only.

## 6. Transformation — dbt

**Now:** `dbt-postgres`. The container starts, runs `dbt run`, and exits; the
SQL executes inside the environment's Postgres. The job has no idle cost, but
the work lands on a resident process that also serves reads — the trade-off
ADR-0008 accepts, and whose limit is the first lakehouse trigger. Models prefer
portable SQL, because a later move to DuckDB has to port them.

**When the lakehouse enters:** DuckDB reads the table format directly from
object storage, processes with a configured `memory_limit` (spilling to disk
rather than dying), and writes back. Compute becomes fully ephemeral.

Layers: bronze (raw, typed), silver (cleaned, conformed), gold (modelled for
consumption). Each layer's guaranteed schema is a contract — see
[`engineering-protocol.md`](engineering-protocol.md) §16.3.

**The project** is `platform/warehouse/`. For USGS, silver is
`stg_usgs__events` (the latest revision of each event, typed, times in UTC) and
gold is `fct_earthquakes` (earthquakes only, with magnitude and depth classes —
the globe's source) and `agg_earthquakes_daily_region`. Both gold models have an
enforced contract. `dbt build` runs the tests with the models: keys, ranges and
accepted values; reconciliation of row counts between the layers
(`tests/reconcile_*.sql`); and unit tests of the dedup, the region parsing and
the class boundaries. Freshness of bronze (warn 2 h, error 6 h) is checked by
`dbt source freshness`. CI lints and parses the project but runs no model: how
to run it is in [`platform/warehouse/README.md`](../platform/warehouse/README.md).

## 7. Orchestration — Dagster

Assets, lineage, backfill, declarative retries, native dbt and dlt integration.
Metastore in Postgres, since the SQLite default does not serve multiple users.

Until Dagster runs, each pipeline run reports success to Healthchecks.io, which
e-mails the operator when a report is missing
([ADR-0018](adr/0018-pipeline-heartbeat.md); runbook: *Pipeline heartbeat*).

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
pooler are declared the same way when their triggers arrive. Backup is not
configured until the backup trigger (end of M2); the options and their resident
cost are compared in the ADR.

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

Three tools would be excess if introduced together. They enter staged:

| Tool | Role | RAM | Enters when |
|---|---|---|---|
| **Evidence** | curated reports, SQL + Markdown, built in CI | 0 (static) | M4 — first |
| **Streamlit + pydeck** | the globe and interactive apps | 200–250 MB | M6, once the globe exists |
| **Grafana** | time series, pipeline health, alerting | 150 MB | when there is something to monitor that Dagster alerts do not cover |

Evidence is MIT-licensed with no per-seat cost. It is built for reviewed
reports, not ad-hoc exploration.

Two cautions: in static build mode the data is **embedded in the site** as
Parquet, and the open-source version has **no row-level security**, so
segmentation per client means one build per client with filtered SQL — not a
permission inside the app. It also has **no authentication layer**: it must sit
behind Cloudflare Access or Tailscale.

Streamlit re-executes its script on every interaction, so it requires
disciplined `st.cache_data`. It also has no native auth.

Metabase is the better self-service BI tool for an SMB but costs 600 MB–1 GB on
the JVM. Documented as a conscious upgrade: raise the VPS to 8 GB and add it
when a client needs ad-hoc exploration.

## 9a. Environments

Three, decided in [ADR-0007](adr/0007-three-environments.md).

| Environment | Where | What runs there |
|---|---|---|
| `dev` | code on the operator's machine, data in staging | dbt and dlt run from the machine's `uv` environments against the `lagom_dev` database in staging's Postgres, through `kubectl port-forward` over the tailnet; unit tests need no database; manifests are checked with a server-side dry run ([ADR-0014](adr/0014-develop-against-staging.md)) |
| `staging` | namespace on the node | own Postgres `Cluster` mirroring prod's configuration, holding two databases: `lagom` for staging's pipeline and `lagom_dev` for the developer, who cannot connect to `lagom`; own secrets; a ResourceQuota (768Mi of memory requests, 1536Mi of limits, 10 Pods) and a LimitRange ([`platform/infra/postgres-staging/`](../platform/infra/postgres-staging/)); the pipeline as one CronJob, `usgs-pipeline` ([`cronjob-usgs.yaml`](../platform/infra/postgres-staging/cronjob-usgs.yaml)): dlt, then dbt, as init containers, then a heartbeat ping to Healthchecks.io ([ADR-0018](adr/0018-pipeline-heartbeat.md)), applied by Argo CD from `main` and pinned to staging's image digests ([ADR-0015](adr/0015-images-on-ghcr.md)). **No Dagster** — two orchestrators exceed the ceiling |
| `prod` | namespace on the node | the full stack |

**Promotion** is by image digest: staging and prod each pin their own, so a new
image reaches staging through one pull request and prod through another, both
from `main` ([ADR-0015](adr/0015-images-on-ghcr.md)). CI enforces the order:
[`tools/promotion_check.py`](../tools/promotion_check.py) fails a change whose
prod manifests pin an image without a digest, or a digest staging had not
pinned on `main` before that change — Postgres's `imageName` included. It
cannot see whether staging's run succeeded; the operator confirms that before
opening the prod pull request.

**Images.** Two, built by [`images.yml`](../.github/workflows/images.yml) on a
native arm64 runner: `ghcr.io/filipefantini/lagom-usgs` (the dlt pipeline,
[`services/usgs/Dockerfile`](../services/usgs/Dockerfile)) and
`ghcr.io/filipefantini/lagom-warehouse` (`dbt build`,
[`platform/warehouse/Dockerfile`](../platform/warehouse/Dockerfile)). A pull
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

Deferred with a trigger: enters with the first external reader (M4). A light
agent (`cloudflared`, ~30 MB) opens an **outbound-only** connection. Access puts
identity in front with per-application policy. The partner gets a link, logs in,
and sees the dashboard — no install, with WAF and rate limiting included.

### Signed URL

**Requires object storage, so it is unavailable until the lakehouse trigger**
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
default. **Not yet granted:** the privileges are to come from dbt, which will
grant `SELECT` on every gold model and `USAGE` on the `gold` schema each time
it builds one, since a rebuilt table loses the grants of the one it replaces.
Until then the role exists and can read nothing. A consumer gets its own login role inside that group
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

The node shows **3.8 GB** of RAM to the OS (3817 MB; the rest of the nominal
4 GB is reserved by firmware and kernel). Two budgets share it, kept apart
because they are enforced differently.

### Node overhead — outside Kubernetes, enforced by nothing

Measured on 2026-10-12 with the cluster idle and only k3s's own system pods
running (RSS from `ps`):

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

The estimate of 300 MB was the commonly quoted figure for k3s; on this node the
server process alone is twice that, and the container runtime was missing from
the count. RSS overstates slightly because shared pages are counted per process;
it is the conservative measure.

### Pod requests — the CI ceiling

**Ceiling enforced in CI: 2.2 GB of declared requests.** A change that would
exceed it fails the build — see
[`engineering-protocol.md`](engineering-protocol.md) §16.5. The arithmetic,
from the overhead table above: 3.8 GB visible − ~1.5 GB outside Kubernetes
(2026-10-17, by RSS) leaves ~2.3 GB for pods; the ceiling sits ~100 MB under
that, and RSS overstates shared pages, so the real margin is larger
([ADR-0016](adr/0016-ci-ceiling-2-2-gb.md), superseding the 2.6 GB of
[ADR-0011](adr/0011-memory-viability-on-4gb.md)). M2 fits: 2,034 MiB with every
ephemeral job counted as running at once, ~220 MiB to spare; **M3 as planned
does not** (Dagster's 600 MB takes it ~380 MiB over), so
the move to the 8 GB node is expected then — the trigger is in the
[roadmap](roadmap.md).

**How CI enforces it.** [`tools/resource_budget.py`](../tools/resource_budget.py)
runs on every pull request ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)).
It renders every Application the way Argo CD does and fails if any container
lacks a memory request, a memory limit, or a CPU request (for a CloudNativePG
`Cluster`, whose Pods the operator creates, its `spec.resources` and
`spec.instances` stand in for the Pod spec), or if the total
exceeds the ceiling above, which it reads from this file. The total is resident
requests, plus **every ephemeral job at once**, plus **170 MiB for components k3s
installs outside Git**: CoreDNS and metrics-server declare 70 MiB each; Traefik
and local-path declare nothing and were measured at ~20 and ~10 MiB.

**Known exception:** those k3s components are not in Git, so the check cannot
see them, and Traefik, local-path, metrics-server, and servicelb declare no
memory limit. Bringing them under the rule through k3s's `HelmChartConfig` is an
open item in the roadmap.

**Core (M1–M3)** — workloads that run as pods:

| Component | Request | Source |
|---|---|---|
| kube-system (CoreDNS, Traefik, metrics-server, local-path) | ~65 MB | measured idle; Traefik 20 MB of it |
| Argo CD (no Dex) | 608 MB | set from measurement with three Applications: application-controller 290–465 MiB before `GOMEMLIMIT`, 190–285 MiB after (request 384, limit 640, `GOMEMLIMIT` 540MiB), repo-server ~105, server ~37, redis ~10 ([ADR-0009](adr/0009-argocd-bootstrap-and-self-management.md)) |
| CloudNativePG operator | 64 MB | measured 24 MiB with no Cluster, 31 MiB reconciling one (request 64, limit 192, `GOMEMLIMIT` 150MiB) ([ADR-0012](adr/0012-cloudnative-pg.md)) |
| Postgres (prod `Cluster`, 1 instance) | 300 MB | request 300 MiB, limit 512 MiB; `shared_buffers` 96MB, `max_connections` 25, `work_mem` 4MB, `maintenance_work_mem` 32MB, `effective_cache_size` 256MB, instance manager `GOMEMLIMIT` 96MiB. Measured idle on 2026-10-16: pod working set 47 MiB, cgroup 55 MiB (25 anonymous, 25 page cache), instance manager ~62 MiB RSS including shared pages. The request is kept for dbt load, measured in M2. Counted by the CI check, which reads the `Cluster` object because the operator creates its Pods ([`platform/infra/postgres-prod/`](../platform/infra/postgres-prod/cluster.yaml)) |
| Dagster | 600 MB | measured in a spike: ~550 MiB resident with real libraries ([ADR-0011](adr/0011-memory-viability-on-4gb.md)) |
| **Core requests** | **~1.65 GB** | |
| **Left within the ceiling for ephemeral jobs** | **~0.55 GB** | |

Staging adds ~300 MB for its own Postgres
([ADR-0007](adr/0007-three-environments.md)): a second `Cluster` with the same
request and limit as prod's, which the CI check counts like the first
([`platform/infra/postgres-staging/`](../platform/infra/postgres-staging/cluster.yaml)).
That leaves **~0.25 GB** for jobs. Staging's ResourceQuota caps what its jobs
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
total rose by 288 MiB, to 2,034 of the 2,253 MiB ceiling. The sum overstates
jobs whose schedules never meet, which is the safe error for a memory gate.
The 256 MiB is a starting
value. First scheduled run, 2026-10-18 20:30 (8 new events, 15 s): one
kubelet sample per container gave dlt ~60 MiB and dbt ~151 MiB — a floor,
not a peak, since the stats refresh every ~10 s; the request stays until a
longer run is sampled. dbt's SQL runs inside Postgres while every layer
lives there ([ADR-0008](adr/0008-postgres-for-all-layers.md)). Sealed Secrets
declares 32 MB and uses 16 MiB measured ([ADR-0010](adr/0010-sealed-secrets.md)), small enough to leave
the totals above unchanged at this precision. Evidence runs in CI.

**Full design**, adding what enters by trigger:

| Addition | RAM |
|---|---|
| NATS + Redpanda Connect | 120 MB |
| Streamlit | 250 MB |
| Grafana | 150 MB |
| PgBouncer | 5 MB |
| **Core + staging + additions** | **~2.45 GB of requests** |
| **Left within the ceiling for ephemeral jobs** | **none — ~0.25 GB over** |

The full design no longer leaves meaningful room for jobs on this node. That is
the measured cost of the overhead above, recorded here rather than discovered
when the additions arrive. The vertical fallback is in
[ADR-0002](adr/0002-single-node-k3s-hetzner.md): CAX21, 8 GB, one reboot.

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
Console).

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
sudo tailscale up --hostname=lagom-shared-01
```

`tailscale up` prints a login URL. The operator opens it, signs in, and approves
the machine. **No auth key is involved**, so no credential passes through a
script or a chat. The trade-off is that the step is interactive — fine for one
node; an unattended rebuild would use a single-use, short-lived auth key.

Then, in the Tailscale admin console: *Machines → lagom-shared-01 → Disable key
expiry*. A device must re-authenticate every 180 days by default; on a server
that silently drops it from the tailnet, and the cluster's API with it.

On the operator's machine: install the Tailscale app
(`brew install --cask tailscale-app`, which asks for the macOS admin password)
and sign in to the same tailnet.

**Verify:**

```bash
tailscale status                   # both machines listed
tailscale ping lagom-shared-01     # "via <public-ip>:41641" is direct; "via DERP(...)" is relayed
ssh <admin-user>@lagom-shared-01 hostname
```

The first pings may go through a DERP relay until NAT traversal finds a direct
path; on 2026-10-12 it became direct within seconds. A path that stays on DERP
works, only slower.

The node is `lagom-shared-01.<tailnet>.ts.net`, `<node-tailnet-ip>`; `tailscale
status` on either machine prints both.

### Install k3s (M1)

Configuration first, as a file, so the install is declarative and re-runnable;
then the official installer with a pinned version:

```bash
sudo install -d -m 0755 /etc/rancher/k3s
sudo tee /etc/rancher/k3s/config.yaml >/dev/null <<'EOF'
node-name: lagom-shared-01
tls-san:
  - lagom-shared-01.<tailnet>.ts.net
  - <node-tailnet-ip>
secrets-encryption: true
EOF
sudo chmod 0600 /etc/rancher/k3s/config.yaml
curl -sfL https://get.k3s.io -o /tmp/k3s-install.sh
sudo INSTALL_K3S_VERSION="v1.36.5+k3s1" sh /tmp/k3s-install.sh
```

**Why it works.** The installer creates the `k3s` systemd unit; on every start
k3s reads `config.yaml`, where each key is the long form of a command-line flag.

- `tls-san` adds names to the API server's certificate. `kubectl` checks that
  the name it connects to is in the certificate, so the tailnet name must be
  listed or every connection over Tailscale fails TLS verification.
- `secrets-encryption` encrypts Secret objects in the datastore (SQLite) with a
  key generated on the node. It protects a copy of the datastore — a stolen
  disk image or backup. It does not protect against root on the node, which
  holds the key.
- The version is the `stable` channel on 2026-10-12. Upgrading is a deliberate
  change, preceded by a staging rebuild ([ADR-0007](adr/0007-three-environments.md)).

**Memory limit for the Go runtime.** Without it, `k3s-server` grew to 1.2 GB
holding memory it did not use ([ADR-0011](adr/0011-memory-viability-on-4gb.md)).
A systemd drop-in survives reinstalls of k3s, unlike the installer's
environment file, which the installer rewrites:

```bash
sudo install -d -m 0755 /etc/systemd/system/k3s.service.d
printf '%s\n' '[Service]' 'Environment=GOMEMLIMIT=900MiB' \
  | sudo tee /etc/systemd/system/k3s.service.d/memory.conf
sudo systemctl daemon-reload && sudo systemctl restart k3s
kubectl get --raw /metrics | grep '^go_gc_gomemlimit_bytes'   # 9.437184e+08
```

**Check the limit still has headroom** whenever the cluster gains a component.
If collections run several times per second and the node's CPU is near 100%
while pods use little, the runtime has hit the limit — raise it and record
the measurement ([ADR-0011](adr/0011-memory-viability-on-4gb.md) notes):

```bash
kubectl get --raw /metrics | grep -E '^go_(memstats_sys_bytes|gc_gomemlimit_bytes|goroutines|gc_duration_seconds_count) '
kubectl get --raw /api/v1/nodes/lagom-shared-01/proxy/stats/summary   # CPU of "kubelet" (k3s) vs "pods"
```

Restarting k3s does not stop running containers (`KillMode=process`); only the
API is unavailable for a few seconds.

k3s defaults are kept, including metrics-server, which `kubectl top` needs to
measure the budget in §11. Traefik's LoadBalancer is served by k3s's servicelb
on ports 80 and 443 of the public address, and the API (6443) and kubelet
(10250) listen on all interfaces. **The Hetzner firewall is what keeps them
private** — which is why the check below probes from outside.

**Verify:**

```bash
sudo k3s kubectl get nodes        # lagom-shared-01   Ready
sudo k3s secrets-encrypt status   # Encryption Status: Enabled
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

Then *Machines → lagom-shared-01 → Edit ACL tags → `tag:lagom-node`*.

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
(10250), and Traefik (80, 443) off the internet, since k3s listens on every
interface. Outbound is unrestricted. Tailscale still connects directly, because
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
for p in 22 6443 10250; do nc -z -G 5 -w 5 lagom-shared-01 $p && echo "$p OPEN" || echo "$p closed"; done
```

Expected: every public port closed while the control succeeds; over the tailnet
22 and 6443 open, 10250 closed. On 2026-10-12 a listener on the operator's
tailnet address was also probed from the node: refused, with a local control
connection to the same listener succeeding.

### Operator kubeconfig (M1)

```bash
umask 077 && mkdir -p ~/.kube
ssh <admin-user>@lagom-shared-01 'sudo cat /etc/rancher/k3s/k3s.yaml' \
  | sed -e 's#https://127.0.0.1:6443#https://lagom-shared-01.<tailnet>.ts.net:6443#' \
        -e 's#: default$#: lagom-shared-01#' > ~/.kube/config
kubectl get nodes
```

This file is the **cluster-admin credential** — a client certificate with every
right in the cluster. It never goes to Git or chat, `umask 077` keeps it
readable only by its owner, and it is not shared: per-developer RBAC replaces it
for anyone else (M7). The command overwrites `~/.kube/config`; merge instead if
one already exists.

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

Expected within a few minutes: `root`, `argocd`, and `hello` all `Synced` and
`Healthy`. `root` syncing is also the proof that Argo CD can read the repository.

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

**Restore on a rebuild** — before Argo CD syncs anything sealed. *Not yet
exercised; it is part of the M2 disaster-recovery drill.*

```bash
kubectl apply -f sealed-secrets-key.yaml        # the Document from 1Password
kubectl -n kube-system delete pod -l app.kubernetes.io/name=sealed-secrets   # reload keys
```

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

### Sections to fill as the platform is built

- **Backup and restore** — what is backed up, where, how often, and the
  **measured** restore procedure. (M2)
- **Disaster recovery** — rebuild from Git plus the latest backup, with measured
  RTO. (M2)
- **Secret rotation** — how to rotate a source credential and a database
  password. (M2)
- **On failure** — where to look: Argo CD sync state, Dagster run history, pod
  logs. (M3)

Each section is written when the corresponding milestone is implemented, with
commands that were actually run — never from memory.
