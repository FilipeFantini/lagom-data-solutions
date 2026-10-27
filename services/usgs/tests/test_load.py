"""Loading fixtures through the real dlt pipeline into a throwaway DuckDB file."""

import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import duckdb
import pytest
import requests_mock as rm
from dlt.common.destination import Destination
from dlt.pipeline.exceptions import PipelineStepFailed

import pipeline
from conftest import (
    NEWEST_UPDATED_PARAM,
    NOW,
    QUERY_URL,
    REVISED_UPDATED_PARAM,
    Page,
    load_fixture,
)

FIRST_LOAD: dict[int, Page] = {1: "page1.json", 3: "page2.json", 5: "page_empty.json"}
SINCE = NOW - timedelta(days=2)
Serve = Callable[[dict[int, Page]], None]
Queries = Callable[[], list[dict[str, str]]]


def query(destination: Destination[Any, Any], sql: str) -> list[tuple[Any, ...]]:
    path = destination.config_params["credentials"]
    with duckdb.connect(str(path), read_only=True) as connection:
        return connection.execute(sql).fetchall()


def load(destination: Destination[Any, Any], config_path: Path, **kwargs: Any) -> int:
    return pipeline.run(destination, now=kwargs.pop("now", NOW), config_path=config_path, **kwargs)


def test_load_produces_typed_columns_and_no_child_table(
    serve: Serve, destination: Destination[Any, Any], config_path: Path
) -> None:
    serve(FIRST_LOAD)

    rows = load(destination, config_path)

    assert rows == 4
    assert query(destination, "select count(*) from bronze.usgs_events") == [(4,)]
    types = dict(
        query(
            destination,
            "select column_name, data_type from information_schema.columns "
            "where table_schema = 'bronze' and table_name = 'usgs_events'",
        )
    )
    # Epoch milliseconds stay integers in bronze; silver converts them.
    assert types["properties__mag"] == "DOUBLE"
    assert types["properties__time"] == "BIGINT"
    assert types["properties__updated"] == "BIGINT"
    assert types["geometry__coordinates"] == "JSON"
    tables = {
        name
        for (name,) in query(
            destination,
            "select table_name from information_schema.tables where table_schema = 'bronze'",
        )
    }
    assert tables == {
        "usgs_events",
        "_dlt_loads",
        "_dlt_pipeline_state",
        "_dlt_version",
    }
    # The odd record (null magnitude and place) loads as nulls, not as a failure.
    assert query(
        destination,
        "select id from bronze.usgs_events "
        "where properties__mag is null and properties__place is null",
    ) == [("us6000u1j7",)]
    coordinates = query(
        destination,
        "select geometry__coordinates::VARCHAR from bronze.usgs_events where id = 'us6000u0y1'",
    )
    assert coordinates == [("[-82.5592,-43.3981,10]",)]


def test_all_pages_are_requested_and_loaded(
    serve: Serve, queries: Queries, destination: Destination[Any, Any], config_path: Path
) -> None:
    serve(FIRST_LOAD)

    load(destination, config_path)

    assert [q["offset"] for q in queries()] == ["1", "3", "5"]
    assert {q["limit"] for q in queries()} == {"2"}
    assert query(destination, "select id from bronze.usgs_events order by id") == [
        ("nn00924954",),
        ("us6000tzh0",),
        ("us6000u0y1",),
        ("us6000u1j7",),
    ]


def test_row_repeated_across_pages_is_loaded_once(
    serve: Serve, destination: Destination[Any, Any], config_path: Path
) -> None:
    # A revision arriving mid-pagination shifts the offsets, so page 2 repeats an event.
    page2 = load_fixture("page2.json")
    page2["features"].insert(0, load_fixture("page1.json")["features"][1])
    serve({1: "page1.json", 3: page2, 5: "page_empty.json"})

    load(destination, config_path)

    assert query(
        destination,
        "select count(*), count(distinct (id, properties__updated)) from bronze.usgs_events",
    ) == [(4, 4)]


def test_backfilling_the_same_window_twice_adds_no_rows(
    serve: Serve, destination: Destination[Any, Any], config_path: Path
) -> None:
    serve(FIRST_LOAD)
    window = {"since": SINCE, "until": NOW}

    load(destination, config_path, **window)
    load(destination, config_path, **window)

    assert query(destination, "select count(*) from bronze.usgs_events") == [(4,)]


def test_default_run_repeated_adds_no_rows(
    serve: Serve, destination: Destination[Any, Any], config_path: Path
) -> None:
    serve(FIRST_LOAD)

    load(destination, config_path)
    load(destination, config_path, now=NOW + timedelta(hours=1))

    assert query(destination, "select count(*) from bronze.usgs_events") == [(4,)]


def test_backfill_leaves_the_stored_cursor_alone(
    serve: Serve, queries: Queries, destination: Destination[Any, Any], config_path: Path
) -> None:
    serve(FIRST_LOAD)

    load(destination, config_path, since=SINCE, until=NOW)
    load(destination, config_path)

    first_run, second_run = queries()[0], queries()[3]
    assert first_run["updatedafter"] == "2026-10-14T12:00:00"
    assert second_run["updatedafter"] == "2026-09-16T12:00:00"  # initial value, not the backfill's


def test_revision_adds_a_row_and_advances_the_cursor(
    serve: Serve, queries: Queries, destination: Destination[Any, Any], config_path: Path
) -> None:
    serve(FIRST_LOAD)
    load(destination, config_path)

    serve({1: "page_revision.json", 3: "page_empty.json"})
    rows = load(destination, config_path, now=NOW + timedelta(hours=1))

    # Only the revised event is new: the repeated one at the cursor edge is dropped.
    assert rows == 1
    assert query(destination, "select count(*) from bronze.usgs_events") == [(5,)]
    history = query(
        destination,
        "select properties__mag from bronze.usgs_events where id = 'us6000tzh0' "
        "order by properties__updated",
    )
    assert history == [(4.6,), (4.3,)]

    serve({1: "page_empty.json"})
    load(destination, config_path, now=NOW + timedelta(hours=2))

    sent = [q["updatedafter"] for q in queries() if q["offset"] == "1"]
    assert sent == ["2026-09-16T12:00:00", NEWEST_UPDATED_PARAM, REVISED_UPDATED_PARAM]


def test_type_change_in_the_source_fails_the_run(
    serve: Serve, destination: Destination[Any, Any], config_path: Path
) -> None:
    serve(FIRST_LOAD)
    load(destination, config_path)

    page = load_fixture("page_revision.json")
    page["features"][0]["properties"]["mag"] = "not a number"
    serve({1: page, 3: "page_empty.json"})

    with pytest.raises(PipelineStepFailed, match="properties__mag"):
        load(destination, config_path, now=NOW + timedelta(hours=1))
    assert query(destination, "select count(*) from bronze.usgs_events") == [(4,)]


@pytest.mark.parametrize(("hours", "fails"), [(5, False), (6, True), (48, True)])
def test_empty_backfill_window_fails_only_from_the_threshold(
    serve: Serve, destination: Destination[Any, Any], config_path: Path, hours: int, fails: bool
) -> None:
    serve({1: "page_empty.json"})
    window = {"since": NOW - timedelta(hours=hours), "until": NOW}

    if fails:
        with pytest.raises(pipeline.EmptyWindowError, match="2026-10-16T12:00:00"):
            load(destination, config_path, **window)
    else:
        assert load(destination, config_path, **window) == 0


def test_first_run_with_nothing_returned_fails_naming_the_window(
    serve: Serve, destination: Destination[Any, Any], config_path: Path
) -> None:
    serve({1: "page_empty.json"})

    with pytest.raises(pipeline.EmptyWindowError, match="2026-09-16T12:00:00"):
        load(destination, config_path)


def test_empty_window_is_measured_from_the_stored_cursor(
    serve: Serve, destination: Destination[Any, Any], config_path: Path
) -> None:
    serve(FIRST_LOAD)
    load(destination, config_path)  # cursor now 2026-10-16T09:04:58
    serve({1: "page_empty.json"})

    assert load(destination, config_path, now=NOW) == 0  # 2 h 55 min since the cursor
    with pytest.raises(pipeline.EmptyWindowError, match="2026-10-16T09:04:58"):
        load(destination, config_path, now=NOW + timedelta(hours=4))  # 6 h 55 min


def test_since_and_until_must_be_given_together(
    destination: Destination[Any, Any], config_path: Path
) -> None:
    with pytest.raises(ValueError, match="together"):
        load(destination, config_path, since=SINCE)
    with pytest.raises(ValueError, match="before"):
        load(destination, config_path, since=NOW, until=SINCE)


def test_cursor_is_restored_from_the_destination_when_local_state_is_lost(
    serve: Serve,
    queries: Queries,
    destination: Destination[Any, Any],
    config_path: Path,
    tmp_path: Path,
) -> None:
    # A CronJob pod starts with an empty disk: the cursor must come back from bronze.
    serve(FIRST_LOAD)
    load(destination, config_path)
    shutil.rmtree(tmp_path / "dlt")

    serve({1: "page_empty.json"})
    load(destination, config_path, now=NOW + timedelta(hours=1))

    assert queries()[-1]["updatedafter"] == NEWEST_UPDATED_PARAM


def test_event_without_a_cursor_value_fails_the_run(
    serve: Serve, destination: Destination[Any, Any], config_path: Path
) -> None:
    page = load_fixture("page1.json")
    del page["features"][0]["properties"]["updated"]
    serve({1: page, 3: "page_empty.json"})

    with pytest.raises(PipelineStepFailed, match="updated"):
        load(destination, config_path)


@pytest.mark.parametrize("argument", ["now", "since", "until"])
def test_naive_datetime_is_rejected_naming_the_argument(
    serve: Serve, destination: Destination[Any, Any], config_path: Path, argument: str
) -> None:
    serve({1: "page_empty.json"})  # so that a missing check fails fast instead of at the network
    arguments: dict[str, Any] = {"now": NOW, "since": SINCE, "until": NOW}
    arguments[argument] = arguments[argument].replace(tzinfo=None)

    with pytest.raises(ValueError, match=f"{argument} must be timezone-aware"):
        pipeline.run(destination, config_path=config_path, **arguments)


def test_http_error_on_a_later_page_loads_nothing_and_a_rerun_loads_everything(
    requests_mock: rm.Mocker,
    serve: Serve,
    destination: Destination[Any, Any],
    config_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME__REQUEST_MAX_ATTEMPTS", "1")  # do not wait out dlt's retries
    page1 = load_fixture("page1.json")

    def respond(request: Any, context: Any) -> dict[str, Any]:
        if parse_qs(urlparse(request.url).query)["offset"][0] == "1":
            return page1
        context.status_code = 500
        return {"error": "server error"}

    requests_mock.get(QUERY_URL, json=respond)

    with pytest.raises(PipelineStepFailed):
        load(destination, config_path)

    database = tmp_path / "warehouse.duckdb"
    assert not database.exists() or query(
        destination,
        "select count(*) from information_schema.tables where table_name = 'usgs_events'",
    ) == [(0,)]

    serve(FIRST_LOAD)
    load(destination, config_path)

    assert query(destination, "select count(*) from bronze.usgs_events") == [(4,)]


def test_backfill_after_a_cursor_exists_does_not_move_it(
    serve: Serve, queries: Queries, destination: Destination[Any, Any], config_path: Path
) -> None:
    serve(FIRST_LOAD)
    load(destination, config_path)  # cursor becomes the newest event's `updated`
    until = datetime(2026, 10, 16, 9, 2, tzinfo=UTC)  # after us6000tzh0, before the cursor
    # The backfill is served one event inside its window and one revision newer than the
    # cursor; `until` must keep the revision, and so the cursor, where they were.
    page = load_fixture("page1.json")
    page["features"] = [page["features"][0], load_fixture("page_revision.json")["features"][0]]
    serve({1: page, 3: "page_empty.json"})
    load(destination, config_path, since=SINCE, until=until)
    serve({1: "page_empty.json"})
    load(destination, config_path, now=NOW + timedelta(hours=1))

    assert queries()[-1]["updatedafter"] == NEWEST_UPDATED_PARAM
