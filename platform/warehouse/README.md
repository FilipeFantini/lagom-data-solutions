# warehouse — the dbt project

The single dbt project ([ADR-0006](../../docs/adr/0006-monorepo-layout.md)). It
reads bronze, which dlt loads, and builds silver and gold in the same Postgres
([ADR-0008](../../docs/adr/0008-postgres-for-all-layers.md)).

| Layer | Schema | Models | What it guarantees |
|---|---|---|---|
| bronze | `bronze` | none: declared as a `source` | raw, typed, every revision of an event |
| silver | `silver` | `models/staging/usgs/stg_usgs__events` | one row per event, its latest revision, typed and renamed, times in UTC `timestamptz`; every event type |
| gold | `gold` | `models/marts/seismic/fct_earthquakes`, `agg_earthquakes_daily_region` | the earthquakes only, with magnitude and depth classes; and per UTC day and region counts. **Contract enforced** |

Models are tables, rebuilt whole on each run: at about 300 000 events a year
that costs seconds, and it makes a re-run give the same result by construction
(protocol 16.1). `macros/generate_schema_name.sql` makes the schemas exactly
`silver` and `gold`, and stops the run for a model that names none.

## What the models decide

- **Latest revision.** Bronze keeps every revision of an event. Silver ranks
  them by `updated` and keeps the first, so a revised magnitude or a change from
  `automatic` to `reviewed` replaces the older row.
- **Region** is the text after the last comma of `place`, trimmed; a place with
  no comma is its own region (`Fiji region`).
- **Classes.** Magnitude: below 2 micro, 4 minor, 5 light, 6 moderate, 7 strong,
  8 major, from 8 great. Lower bounds are inclusive. Depth: below 70 km shallow,
  up to 300 km intermediate, deeper deep. A null stays null, so the not-null
  tests on magnitude, depth, and both classes fail instead of filing it under a
  class. A place ending in a comma gives a null region, not an empty one.
- **Time.** `to_timestamp` reads epoch milliseconds as UTC; no timestamp is
  naive. The daily aggregate cuts the day explicitly at UTC. No SQL here reads
  the clock; only the freshness check below compares with `now`, because that
  is what freshness means.

## Tests

`dbt build` runs them in dependency order and stops a model's dependents when it
fails.

| Kind | Where | What |
|---|---|---|
| Contract | `_seismic__models.yml` | both gold models: column names and types are compared with the SQL before the table is written |
| Generic | the `_*__models.yml` files | `unique`, `not_null`, `accepted_values` on keys and classes; `value_between` (`tests/generic/`) on latitude and longitude |
| Reconciliation | `tests/reconcile_*.sql` | silver rows equal distinct ids in bronze; gold rows equal silver earthquakes; the daily counts add up to gold rows; no gold id is missing from silver |
| Privileges | `tests/gold_reader_privileges.sql` | `gold_reader` can read every gold relation and use the `gold` schema, reads nothing in bronze or silver, and writes nowhere — checked in the database's catalogue, after both gold models are built |
| Unit | `unit_tests:` in the model files | given rows and expected rows: latest revision, region parsing, type conversion, class boundaries, UTC day boundary |
| Freshness | `_usgs__sources.yml` | newest `updated` in bronze: warn after 2 hours, error after 6. **Run separately**, `dbt source freshness`; `dbt build` does not |

A reconciliation test reads bronze live. If dlt loads between the silver build
and the test, it fails for a reason that is not a defect: run the build again.

What the tests do not cover: `dbt parse` in CI reads the project but never
queries, so only a run against a database proves the SQL, the contract and the
tests. Staging runs it after every dlt load as the `transform` init container of the CronJob
[`platform/infra/postgres-staging/cronjob-usgs.yaml`](../../platform/infra/postgres-staging/cronjob-usgs.yaml);
the first such run has not happened yet.

## Run it against dev

Per [ADR-0014](../../docs/adr/0014-develop-against-staging.md) the code runs on
your machine and the data lives in `lagom_dev`, in staging's Postgres. Get the
password into the shell and forward the port as the runbook describes
([architecture.md, Postgres, Staging](../../docs/architecture.md#staging)); it
holds the password in `PGPASSWORD`. Then, from the repository root:

```sh
export LAGOM_PG_HOST=127.0.0.1 LAGOM_PG_PORT=15432 LAGOM_PG_USER=lagom_dev \
       LAGOM_PG_DBNAME=lagom_dev LAGOM_PG_SSLMODE=disable
export LAGOM_PG_PASSWORD="$PGPASSWORD"

dbt() { uv run --project platform/warehouse --locked dbt "$@" \
          --project-dir platform/warehouse --profiles-dir platform/warehouse; }
dbt build
dbt source freshness
```

`profiles.yml` is committed because it holds no value: every setting is read
from `LAGOM_PG_*` and none has a default. A missing variable stops dbt naming
it, with one dbt quirk: for `password` dbt falls back to the literal template
text, so a missing `LAGOM_PG_PASSWORD` shows up as Postgres refusing the login,
not as a message naming the variable.

**`sslmode=disable` is deliberate here.** `kubectl port-forward` closed the
tunnel after the first TLS session ended, so a second connection (dbt opens
several) failed. The hop it carries is already encrypted: Tailscale between your
machine and the node, TLS between `kubectl` and the API server. What is given up
is Postgres's own TLS inside that tunnel, the accepted residual. Do not copy
`disable` to a connection that does not go through a port-forward.

Lint, as CI runs it (dialect `postgres`, jinja templater, config in
`.sqlfluff`):

```sh
uv run --project platform/warehouse --locked sqlfluff lint platform/warehouse
```

## Image

`Dockerfile` builds `ghcr.io/filipefantini/lagom-warehouse`, whose entrypoint is
`dbt build` with the project and profiles directories set; extra arguments
(`--select`) are appended. CI builds it and publishes it from `main`
([`images.yml`](../../.github/workflows/images.yml),
[ADR-0015](../../docs/adr/0015-images-on-ghcr.md)). The image carries `tests/`
because `dbt build` runs them. It runs as UID 10001 on a read-only root
filesystem; dbt writes only under `/tmp`, so mount a writable volume there. The
`LAGOM_PG_*` variables are supplied by the job.

## Known limits

- **`region` is USGS's text, not a normalized name.** It is whatever follows the
  last comma of `place`, so California appears as `CA` while other states are
  spelled out (`Alaska`, `Texas`). Seen in the first real build, 2026-10-17.
  Normalizing it needs a lookup the source does not provide; until then,
  aggregates by region compare like with like only within one naming style.
