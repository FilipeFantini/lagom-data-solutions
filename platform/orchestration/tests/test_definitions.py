"""The code location loads, and its graph is the one the ADR describes."""

import os
import subprocess
from pathlib import Path

import pytest
from dagster import AssetKey

WAREHOUSE = Path(__file__).resolve().parents[2] / "warehouse"
# `dbt parse` reads the profile but opens no connection: placeholders suffice.
PARSE_ENV = {
    "LAGOM_LAKE_CATALOG": "ducklake:parse.ducklake",
    "LAGOM_LAKE_DATA_PATH": "parse/",
    "LAGOM_LAKE_METADATA_SCHEMA": "main",
    "LAGOM_R2_ACCESS_KEY_ID": "parse",
    "LAGOM_R2_SECRET_ACCESS_KEY": "parse",
    "LAGOM_R2_ENDPOINT": "https://parse.invalid",
}


@pytest.fixture(scope="module")
def defs(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    logs = tmp_path_factory.mktemp("dbt-logs")
    subprocess.run(
        [
            "dbt",
            "parse",
            "--project-dir",
            str(WAREHOUSE),
            "--profiles-dir",
            str(WAREHOUSE),
            "--target",
            "lake",
            "--log-path",
            str(logs),
            "--quiet",
        ],
        check=True,
        env={**os.environ, **PARSE_ENV},
    )
    from lagom_orchestration.definitions import defs

    return defs


def test_silver_reads_the_dlt_asset(defs) -> None:  # type: ignore[no-untyped-def]
    graph = defs.resolve_asset_graph()
    silver = AssetKey(["silver", "stg_usgs__events"])
    assert AssetKey(["usgs", "events"]) in graph.get(silver).parent_keys


def test_jobs_and_schedules(defs) -> None:  # type: ignore[no-untyped-def]
    assert {j.name for j in defs.resolve_all_job_defs()} >= {"usgs", "lake_maintenance"}
    crons = {s.job_name: s.cron_schedule for s in defs.schedules}  # type: ignore[union-attr]
    assert crons == {"usgs": "*/30 * * * *", "lake_maintenance": "15 4 * * *"}
