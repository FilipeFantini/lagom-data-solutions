"""DuckLake maintenance: compaction and file cleanup (ADR-0023, ADR-0026).

Each 30-minute run writes a few small Parquet files. Merging adjacent files
keeps reads fast and the R2 operation count low; expiring old snapshots and
deleting the files only they referenced keeps the bucket from growing with
history nobody reads.
"""

import duckdb

# Snapshots younger than this stay, so a recent version of any table can
# still be read (time travel) and a reader in flight never loses its files.
SNAPSHOT_RETENTION = "7 days"


def maintenance_statements(alias: str = "lake") -> list[str]:
    """The SQL run against an attached DuckLake, in order."""
    return [
        f"CALL ducklake_merge_adjacent_files('{alias}')",
        f"CALL ducklake_expire_snapshots('{alias}', "
        f"older_than => now() - INTERVAL '{SNAPSHOT_RETENTION}')",
        f"CALL ducklake_cleanup_old_files('{alias}', cleanup_all => true)",
    ]


def run_maintenance(connection: duckdb.DuckDBPyConnection, alias: str = "lake") -> None:
    for statement in maintenance_statements(alias):
        connection.execute(statement)


def _require(name: str) -> str:
    import os

    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"environment variable {name} is not set")
    return value


def _literal(value: str) -> str:
    """A SQL string literal. DuckDB takes no parameters in CREATE SECRET or ATTACH."""
    return "'" + value.replace("'", "''") + "'"


def attach_lake(alias: str = "lake") -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB with the environment's DuckLake attached.

    Reads the same variables as the dbt `lake` target (platform/warehouse/
    profiles.yml), so maintenance and transformation see the same catalog.
    The statements hold the R2 key, so they are never logged.
    """
    connection = duckdb.connect()
    for extension in ("ducklake", "httpfs", "postgres"):
        connection.execute(f"INSTALL {extension}; LOAD {extension}")
    key_id = _literal(_require("LAGOM_R2_ACCESS_KEY_ID"))
    secret = _literal(_require("LAGOM_R2_SECRET_ACCESS_KEY"))
    endpoint = _literal(_require("LAGOM_R2_ENDPOINT").removeprefix("https://"))
    connection.execute(
        f"CREATE SECRET r2 (TYPE s3, KEY_ID {key_id}, SECRET {secret}, "
        f"ENDPOINT {endpoint}, REGION 'auto', URL_STYLE 'path')"
    )
    catalog = _literal(_require("LAGOM_LAKE_CATALOG"))
    data_path = _literal(_require("LAGOM_LAKE_DATA_PATH"))
    metadata_schema = _literal(_require("LAGOM_LAKE_METADATA_SCHEMA"))
    connection.execute(
        f"ATTACH {catalog} AS {alias} (DATA_PATH {data_path}, METADATA_SCHEMA {metadata_schema})"
    )
    return connection
