# usgs — earthquake events

Extraction and load of earthquake events from the USGS FDSN event web service
into the `bronze` schema. Part of M2; staging runs it as the first init container of the CronJob
[`platform/infra/postgres-staging/cronjob-usgs.yaml`](../../platform/infra/postgres-staging/cronjob-usgs.yaml).

| | |
|---|---|
| **Source** | `https://earthquake.usgs.gov/fdsnws/event/1/query`, `format=geojson`. No key, no authentication. The static summary feeds are not used: they have no `updatedafter` and cannot be paged or backfilled. |
| **Destination** | dlt `postgres` destination, dataset `bronze`, table `usgs_events` |
| **Freshness threshold** | 2 hours — the newest `properties__updated` in bronze may not be older than that. Asserted by dbt in the next step, not here. |
| **Volume** | about 9 events an hour, roughly 300 000 a year |

## How it works

`ingestion/source.yaml` declares the source — URL, paginator, cursor, key,
write disposition, column types — as data. `ingestion/pipeline.py` loads it with
`yaml.safe_load`, validates it, adds the few things YAML cannot express, and runs
a dlt pipeline. Everything about the source lives in the YAML; the Python
contains no URL, no window, and no threshold.

**Pagination.** The API pages with `limit` (at most 20 000) and `offset`
(1-based). dlt's offset paginator advances `offset` by `limit` and stops at the
first empty page. The API answers a page past the end with HTTP 200 and an
empty `features` list, so that last request is the stop signal.

**Ordering.** `orderby=time-asc`. FDSN offers no ordering by `updated`, and
none is needed: dlt tracks the cursor as the maximum it has seen, in any order.
A stable order is what offset pagination needs.

**Cursor.** `properties.updated`, epoch milliseconds, sent to the API as
`updatedafter` in ISO 8601 UTC. dlt stores the cursor in its pipeline state,
which it also writes to the destination (`_dlt_pipeline_state`), so a
CronJob pod with no disk restores it from Postgres and the cursor can be
inspected with SQL. `updatedafter` ignores fractions of a second, so the request
is cut to whole seconds and the API re-sends the events of the last second; the
merge key removes them.

**Write disposition: `merge` on `(id, properties__updated)`.** An event is not
final when it is first published. USGS revises magnitude, location, and status
(`automatic` to `reviewed`) for days, and each revision carries a new `updated`.
Bronze is the raw record, so it keeps every revision: a revised event is a new
row, and silver decides which revision is current. Because `updated` is part of
the key, loading the same revision twice replaces its own row instead of adding
one — re-running a window inserts nothing new, and an overlap between runs is
harmless. `append` would duplicate on every re-run; a key on `id` alone would
overwrite history.

**Types.** `properties` becomes typed columns (`properties__mag`,
`properties__place`, ...). `time` and `updated` stay `BIGINT` epoch
milliseconds in bronze; silver converts them. The API writes a magnitude as `4`
or `4.1` depending on the value, and dlt types a column from the first value it
sees, so the fractional fields (`mag`, `cdi`, `mmi`, `dmin`, `rms`, `gap`) are
declared `double` in the YAML. `schema_contract: data_type: freeze` makes a field
whose type changes fail the run instead of adding a second variant column. A
field that is new to the source is added as a column. A field the source stops
sending is not detected here: its column goes null, and dbt tests in the next
step must catch that.

**Nesting.** `geometry.coordinates` is `[longitude, latitude, depth]`. A list
under a row makes dlt create a child table, one row per element, which would
turn one event into three rows with no meaning. The column hint
`geometry__coordinates: {data_type: json}` keeps it as one `JSON` value;
silver extracts the three numbers. The hint is per column on purpose:
`max_table_nesting` would apply to every list in the payload, including any
the source adds later. A new list then becomes a visible child table instead of
being hidden inside JSON. `properties` is a dict, not a list, so dlt flattens it
into columns whichever way this is set.

## Failing loudly

- An HTTP error, a timeout, or a response that is not valid JSON propagates and
  fails the run. This code has no `except` around the request; the only retry is
  the few attempts dlt's HTTP client makes on a transient error (5xx, 429)
  before it raises.
- A window of `empty_window_hours` (6) or more that yields no new events raises
  `EmptyWindowError` naming the window. The feed averages about 9 events an
  hour, so six empty hours mean an outage or a cursor problem, not a quiet
  period. The window runs from the cursor the request started at to `now`.
  "No new events" counts rows that survive the incremental filter, so a window
  holding only the event already stored at the cursor also counts as empty.
- A type change in the payload fails the run, naming the column.
- An event with no `properties.updated` raises (`on_cursor_value_missing: raise`)
  instead of being skipped or loaded without a cursor.
- The first run reads back `initial_lookback_days` (30) from `now`. Change it in
  the YAML.

## Running it

Everything runs from the repository root, because dlt reads `.dlt/` from the
working directory.

```sh
uv run --project services/usgs python services/usgs/ingestion/pipeline.py --help
```

**Incremental run** (what the CronJob will do):

```sh
uv run --project services/usgs python services/usgs/ingestion/pipeline.py
```

**Backfill a window** of `updated` times, without editing code. `--since` is
included and `--until` is excluded; both need a UTC offset. The stored cursor is
not changed, so a backfill cannot move current data:

```sh
uv run --project services/usgs python services/usgs/ingestion/pipeline.py \
  --since 2026-10-01T00:00:00Z --until 2026-10-02T00:00:00Z
```

The API cannot filter by an upper bound on `updated`, so a backfill reads
everything updated after `--since` and drops what is at or after `--until`
before loading. Pick `--since` close to the window you want.

**Try it without Postgres** — loads into a local DuckDB file named
`usgs.duckdb` in the current directory (git-ignored):

```sh
uv run --project services/usgs python services/usgs/ingestion/pipeline.py \
  --destination duckdb --since 2026-10-16T10:00:00Z --until 2026-10-16T11:00:00Z
```

**Postgres.** Credentials come from dlt's own mechanism and are never in this
repository: the environment variable `DESTINATION__POSTGRES__CREDENTIALS`
(a connection string), or `.dlt/secrets.toml` at the repository root, which is
git-ignored. Do not create `secrets.toml` anywhere else: the ignore rule is
anchored to the root.

dlt sends anonymous usage telemetry unless `RUNTIME__DLTHUB_TELEMETRY=false` is
set. The tests set it; set it wherever the job runs.

## Image

`Dockerfile` builds `ghcr.io/filipefantini/lagom-usgs`, whose entrypoint is
`python ingestion/pipeline.py`: arguments given to the container (`--since`,
`--until`) are passed on. CI builds it and publishes it from `main`
([`images.yml`](../../.github/workflows/images.yml),
[ADR-0015](../../docs/adr/0015-images-on-ghcr.md)). It runs as UID 10001 on a
read-only root filesystem; dlt writes under `/tmp`, so mount a writable volume
there. The credentials are still `DESTINATION__POSTGRES__CREDENTIALS`, supplied
by the job.

## Tests

```sh
uv run --project services/usgs pytest services/usgs
```

The tests load recorded GeoJSON pages (`tests/fixtures/`) through the real dlt
pipeline into a DuckDB file in a temporary directory, with HTTP answered by
`requests-mock`. No test can reach the live API: an unregistered URL raises.
`now` is passed in, never read from the clock inside the code under test. The
fixtures are recorded from the live API, except for the edits listed at the top
of `tests/conftest.py` (an odd record with null magnitude, and a revision, which
cannot be recorded on demand).

Checks as CI runs them:

```sh
uv run --project services/usgs --locked ruff format --check services/usgs
uv run --project services/usgs --locked ruff check services/usgs
uv run --project services/usgs --locked mypy --config-file services/usgs/pyproject.toml services/usgs
uv run --project services/usgs --locked pytest services/usgs
```

## Known limits

- **Offset pagination is not a snapshot.** If an event is revised while a run is
  paging, the offsets shift: an event can appear twice (the merge key removes
  it) or, in principle, be skipped. A skipped event whose `updated` is older than
  the new cursor would not be read again. Nothing here detects it yet; the
  reconciliation step against the API's `count` endpoint is where it would show.
- **Truncated responses happen.** The API occasionally cuts a large response
  short. The result is invalid JSON and the run fails; re-running is safe.
