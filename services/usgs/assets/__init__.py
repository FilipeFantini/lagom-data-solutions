"""Dagster assets for the USGS source (ADR-0026).

`usgs/events` is bronze: one incremental load by the dlt pipeline in
ingestion/, into the environment's DuckLake. Its key is the dbt source
`usgs.events`, so dagster-dbt draws silver and gold downstream of it.

The pipeline module is loaded from its file under a name of its own, so that
`pipeline` and `ingestion` stay free for the next service's code.
"""

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

PIPELINE_PATH = Path(__file__).resolve().parents[1] / "ingestion" / "pipeline.py"


def _load_pipeline() -> ModuleType:
    spec = importlib.util.spec_from_file_location("usgs_pipeline", PIPELINE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the USGS pipeline from {PIPELINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pipeline = _load_pipeline()


@asset(
    key=AssetKey(["usgs", "events"]),
    group_name="usgs",
    kinds={"dlt", "ducklake"},
    description="USGS earthquake events, every revision, as dlt loads them (bronze).",
)
def usgs_events(context: AssetExecutionContext) -> MaterializeResult[None]:
    """Load events updated since dlt's stored cursor into DuckLake.

    The destination is configured by dlt's environment variables
    (DESTINATION__DUCKLAKE__...), set on the run's Pod. An empty window long
    enough to hold events raises, and so fails the run.
    """
    rows: int = pipeline.run("ducklake", now=datetime.now(UTC))
    context.log.info(f"loaded {rows} rows into {pipeline.RESOURCE_NAME}")
    return MaterializeResult(metadata={"rows_loaded": rows})
