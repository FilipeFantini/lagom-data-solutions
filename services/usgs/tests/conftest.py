"""Shared test setup. HTTP is mocked from recorded fixtures: no test reaches the live API.

The fixtures in tests/fixtures are GeoJSON pages recorded from the USGS FDSN event
service on 2026-10-16, with three deliberate edits made by hand and marked here:
  * us6000u1j7 (a real landslide record) has `mag` and `place` set to null, as the odd record;
  * page_revision.json holds a second revision of us6000tzh0 (`updated` moved one hour past the
    newest recorded event, `mag` changed to 4.3), because a revision cannot be recorded on demand;
  * page_revision.json also repeats us6000u0y1 unchanged: the newest event of the first load,
    delivered again at the cursor edge.
Pages are 2 events long (the config's `limit` is overridden to 2), keyed by their `offset`.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import dlt
import pytest
import requests_mock as rm
import yaml
from dlt.common.destination import Destination

import pipeline

FIXTURES = Path(__file__).parent / "fixtures"
QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
# The `updated` value of us6000u0y1, the newest event in page1 + page2, in epoch ms.
NEWEST_UPDATED_MS = 1792141498040
# The same instant as the request parameter: ISO 8601 UTC, whole seconds.
NEWEST_UPDATED_PARAM = "2026-10-16T09:04:58"
REVISED_UPDATED_PARAM = "2026-10-16T10:04:58"

Page = str | dict[str, Any]


def load_fixture(name: str) -> dict[str, Any]:
    page: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return page


@pytest.fixture(autouse=True)
def isolated_dlt_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep pipeline state (the cursor) inside the test's own directory, and stay offline."""
    monkeypatch.setenv("DLT_DATA_DIR", str(tmp_path / "dlt"))
    monkeypatch.setenv("RUNTIME__DLTHUB_TELEMETRY", "false")


@pytest.fixture
def destination(tmp_path: Path) -> Destination[Any, Any]:
    return dlt.destinations.duckdb(str(tmp_path / "warehouse.duckdb"))


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    """source.yaml with a page size of 2, so the fixtures paginate."""
    raw = yaml.safe_load(pipeline.CONFIG_PATH.read_text())
    raw["rest_api"]["resources"][0]["endpoint"]["paginator"]["limit"] = 2
    path = tmp_path / "source.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


@pytest.fixture
def serve(requests_mock: rm.Mocker) -> Callable[[dict[int, Page]], None]:
    """Answer query requests with the page registered for their `offset`."""

    def register(pages: dict[int, Page]) -> None:
        def respond(request: Any, context: Any) -> dict[str, Any]:
            offset = int(parse_qs(urlparse(request.url).query)["offset"][0])
            page = pages[offset]  # an unexpected offset fails the test loudly
            return load_fixture(page) if isinstance(page, str) else page

        requests_mock.get(QUERY_URL, json=respond)

    return register


@pytest.fixture
def queries(requests_mock: rm.Mocker) -> Callable[[], list[dict[str, str]]]:
    """The query parameters of every request made so far, exactly as sent."""

    def sent() -> list[dict[str, str]]:
        return [
            {k: v[0] for k, v in parse_qs(urlparse(r.url).query).items()}
            for r in requests_mock.request_history
        ]

    return sent
