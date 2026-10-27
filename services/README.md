# services/

One directory per workload — a data source being ingested, or any other
self-contained unit of work. Services change often and should affect only
themselves.

```
services/<name>/
  ingestion/     dlt pipeline or Redpanda Connect config
  assets/        Dagster assets for this service
  tests/         fixtures and tests — never calls the live source
  README.md      what it is, its source, its freshness threshold
```

**The test this layout must keep passing:** adding a service creates one
directory here and one under `platform/warehouse/models/`, and changes nothing
else. If a new source ever requires touching more, the layout needs revisiting
with a new ADR.

Checklist for adding one: [`../CONTRIBUTING.md`](../CONTRIBUTING.md).

First service: [`usgs`](usgs/) (earthquakes), in M2. It has `ingestion/` and
`tests/`; `assets/` arrives with Dagster in M3.
