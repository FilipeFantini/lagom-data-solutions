# platform/orchestration/

The platform's Dagster code location ([ADR-0026](../../docs/adr/0026-dagster-one-instance-per-environment.md)).
One image, `lagom-orchestration`, runs both the code server and every run Pod.

| Path | What it is |
|---|---|
| `lagom_orchestration/definitions.py` | The `Definitions`: each service's assets, the dbt project as assets, the jobs and their schedules |
| `lagom_orchestration/lake.py` | Attaching the environment's DuckLake, and its daily maintenance |
| `Dockerfile` | Built from the repository root: it bundles `services/*/ingestion`, `services/*/assets` and `platform/warehouse` |
| `tests/` | The code location loads, and its graph and schedules are the intended ones |

**Jobs.**

- `usgs`, every 30 minutes: `usgs/events` (dlt into DuckLake), then `dbt build`
  on the warehouse's `lake` target.
- `lake_maintenance`, daily at 04:15 UTC: merge small files, expire snapshots
  older than 7 days, and delete the files nothing references.

Both carry the tag `lagom/pipeline: usgs`, which the run queue limits to one
run at a time.

**Configuration** comes from the environment, set on the code server and on
every run Pod:

| Variable | For |
|---|---|
| `DESTINATION__DUCKLAKE__CREDENTIALS__*` | dlt's DuckLake destination: catalog, storage, R2 keys, metadata schema |
| `LAGOM_LAKE_CATALOG`, `LAGOM_LAKE_DATA_PATH`, `LAGOM_LAKE_METADATA_SCHEMA` | the same lake, for dbt and maintenance |
| `LAGOM_R2_ACCESS_KEY_ID`, `LAGOM_R2_SECRET_ACCESS_KEY`, `LAGOM_R2_ENDPOINT` | the environment's R2 token |

**Run it locally** against a DuckLake on disk, with no R2 and no secret. dlt
honours a metadata schema only for a SQL catalog, so a local file uses
`main`:

```bash
cd platform/orchestration && T=$(mktemp -d) && export PYTHONPATH=$PWD/../..:. HOME=$T DAGSTER_HOME=$T DLT_DATA_DIR=$T/dlt DBT_LOG_PATH=$T/dbt-logs \
  DESTINATION__DUCKLAKE__CREDENTIALS__CATALOG="duckdb:///$T/catalog.duckdb" DESTINATION__DUCKLAKE__CREDENTIALS__STORAGE__BUCKET_URL="$T/data" \
  DESTINATION__DUCKLAKE__CREDENTIALS__DUCKLAKE_NAME=lagom DESTINATION__DUCKLAKE__CREDENTIALS__METADATA_SCHEMA=main \
  LAGOM_LAKE_CATALOG="ducklake:$T/catalog.duckdb" LAGOM_LAKE_DATA_PATH="$T/data/" LAGOM_LAKE_METADATA_SCHEMA=main \
  LAGOM_R2_ACCESS_KEY_ID=unused LAGOM_R2_SECRET_ACCESS_KEY=unused LAGOM_R2_ENDPOINT=https://unused.invalid
uv run dbt parse --project-dir ../warehouse --profiles-dir ../warehouse --target lake --quiet
uv run dagster job execute -m lagom_orchestration.definitions -j usgs
rm -rf "$T"
```

On the operator's Mac, 2026-10-28: 9,878 events loaded, dbt `PASS=33`, in 35 s,
with a peak of 356 MiB for the whole process.

**DuckDB is pinned below 2.0.** DuckDB 2.0 removes `Relation.fetchone()`,
which dlt 1.31 calls.
