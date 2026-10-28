"""Dagster's metadata in Postgres can be reached from this environment."""

from sqlalchemy.engine import make_url


def test_the_default_postgres_driver_is_installed() -> None:
    # dagster-postgres builds "postgresql://..." URLs; SQLAlchemy picks the
    # driver. Importing its DBAPI is what failed in staging.
    dialect = make_url("postgresql://dagster@postgres-rw:5432/dagster").get_dialect()
    assert dialect.import_dbapi() is not None
