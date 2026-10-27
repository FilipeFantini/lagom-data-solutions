"""USGS earthquake ingestion.

Builds a dlt `rest_api` source from source.yaml and loads it into bronze. All
time arithmetic takes `now` as a parameter; only the command-line entry point
at the bottom reads the clock.
"""

import argparse
import copy
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import dlt
import yaml
from dlt.common.destination import Destination
from dlt.extract.source import DltSource
from dlt.sources.rest_api import rest_api_source
from dlt.sources.rest_api.typing import RESTAPIConfig

CONFIG_PATH = Path(__file__).with_name("source.yaml")
SOURCE_NAME = "usgs"
RESOURCE_NAME = "usgs_events"


class ConfigError(Exception):
    """source.yaml is missing, malformed, or lacks a required key."""


class EmptyWindowError(RuntimeError):
    """A window long enough to contain events returned none."""


@dataclass(frozen=True)
class Settings:
    dataset_name: str
    initial_lookback_days: int
    empty_window_hours: int


def _require(mapping: Any, key: str, where: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise ConfigError(f"{where}: missing required key '{key}'")
    return mapping[key]


def load_config(path: Path) -> tuple[Settings, dict[str, Any]]:
    """Read source.yaml; return the ingestion settings and the rest_api config."""
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as err:
        raise ConfigError(f"{path}: invalid YAML: {err}") from err

    ingestion = _require(raw, "ingestion", str(path))
    settings = Settings(
        dataset_name=str(_require(ingestion, "dataset_name", "ingestion")),
        initial_lookback_days=_require(ingestion, "initial_lookback_days", "ingestion"),
        empty_window_hours=_require(ingestion, "empty_window_hours", "ingestion"),
    )
    for name in ("initial_lookback_days", "empty_window_hours"):
        value = getattr(settings, name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ConfigError(f"ingestion.{name}: must be a positive integer, got {value!r}")

    rest_api = _require(raw, "rest_api", str(path))
    resources = _require(rest_api, "resources", "rest_api")
    resource = next((r for r in resources if r.get("name") == RESOURCE_NAME), None)
    if resource is None:
        raise ConfigError(f"rest_api.resources: no resource named '{RESOURCE_NAME}'")
    _require(
        _require(resource, "endpoint", RESOURCE_NAME),
        "incremental",
        f"{RESOURCE_NAME}.endpoint",
    )
    return settings, rest_api


def _to_updatedafter(epoch_ms: int) -> str:
    """Cursor (epoch ms) to the ISO 8601 UTC string the API expects.

    USGS ignores sub-second precision in `updatedafter`, so the value is cut to
    whole seconds here; the overlap that results is removed by the merge key.
    """
    return datetime.fromtimestamp(epoch_ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S")


def _epoch_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _incremental(rest_api: dict[str, Any]) -> dict[str, Any]:
    resource = next(r for r in rest_api["resources"] if r["name"] == RESOURCE_NAME)
    incremental: dict[str, Any] = resource["endpoint"]["incremental"]
    return incremental


def _cursor_start_ms(source: DltSource) -> int:
    """The cursor value the request started from: the stored one, or the initial one."""
    wrapper = source.resources[RESOURCE_NAME].incremental
    start = wrapper.incremental.start_value if wrapper and wrapper.incremental else None
    if not isinstance(start, int):
        raise RuntimeError(f"dlt did not expose the start of the incremental cursor: {start!r}")
    return start


def run(
    destination: str | Destination[Any, Any],
    *,
    now: datetime,
    since: datetime | None = None,
    until: datetime | None = None,
    config_path: Path = CONFIG_PATH,
) -> int:
    """Load USGS events into `<dataset_name>.usgs_events`; return the rows loaded.

    Without `since` and `until` the run continues from the stored cursor, or from
    `now - initial_lookback_days` on the first run. With both, it loads events
    updated in [since, until) and leaves the stored cursor untouched.
    """
    for name, moment in (("now", now), ("since", since), ("until", until)):
        if moment is not None and moment.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware (UTC); got naive {moment.isoformat()}")
    if (since is None) != (until is None):
        raise ValueError("since and until must be given together")
    if since is not None and until is not None and since >= until:
        raise ValueError(f"since ({since.isoformat()}) must be before until ({until.isoformat()})")

    settings, rest_api = load_config(config_path)
    config = copy.deepcopy(rest_api)
    incremental = _incremental(config)
    window_end = until or now
    incremental["initial_value"] = _epoch_ms(
        since or now - timedelta(days=settings.initial_lookback_days)
    )
    incremental["convert"] = _to_updatedafter  # a callable: not expressible in YAML
    if until is not None:
        incremental["end_value"] = _epoch_ms(until)

    source = rest_api_source(cast(RESTAPIConfig, config), name=SOURCE_NAME)
    pipeline = dlt.pipeline(
        pipeline_name=SOURCE_NAME,
        destination=destination,
        dataset_name=settings.dataset_name,
    )
    pipeline.run(source)

    trace = pipeline.last_trace
    normalized = trace.last_normalize_info if trace else None
    rows = normalized.row_counts.get(RESOURCE_NAME, 0) if normalized else 0
    window_start = datetime.fromtimestamp(_cursor_start_ms(source) / 1000, UTC)
    if rows == 0 and window_end - window_start >= timedelta(hours=settings.empty_window_hours):
        raise EmptyWindowError(
            f"USGS returned no events updated between {window_start.isoformat()} and "
            f"{window_end.isoformat()}; windows of {settings.empty_window_hours} h or more "
            "are expected to contain events"
        )
    return rows


def _utc_datetime(text: str) -> datetime:
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"'{text}' has no UTC offset; write e.g. 2026-10-16T00:00:00Z"
        )
    return moment


def main(argv: Sequence[str], now: datetime) -> int:
    parser = argparse.ArgumentParser(description="Load USGS earthquake events into bronze.")
    parser.add_argument(
        "--destination", default="postgres", help="dlt destination (default: postgres)"
    )
    parser.add_argument(
        "--since",
        type=_utc_datetime,
        help="backfill: first 'updated' instant to load (ISO 8601 with offset); needs --until",
    )
    parser.add_argument(
        "--until",
        type=_utc_datetime,
        help="backfill: 'updated' instant to stop before; needs --since. Leaves the cursor alone",
    )
    args = parser.parse_args(argv)
    rows = run(args.destination, now=now, since=args.since, until=args.until)
    print(f"loaded {rows} rows into {RESOURCE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], datetime.now(UTC)))
