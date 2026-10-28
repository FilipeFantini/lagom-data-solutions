from lagom_orchestration.lake import _literal, maintenance_statements


def test_maintenance_runs_merge_then_expiry_then_cleanup() -> None:
    statements = maintenance_statements("lake")
    assert [s.split("(")[0] for s in statements] == [
        "CALL ducklake_merge_adjacent_files",
        "CALL ducklake_expire_snapshots",
        "CALL ducklake_cleanup_old_files",
    ]
    assert "INTERVAL '7 days'" in statements[1]


def test_literal_escapes_quotes() -> None:
    assert _literal("it's") == "'it''s'"


def test_maintenance_runs_on_a_real_ducklake(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Attach a DuckLake on disk the way a run does, write to it, and maintain it.

    The R2 secret is created but unused: the data path is local.
    """
    from lagom_orchestration.lake import attach_lake, run_maintenance

    for name, value in {
        "HOME": str(tmp_path),  # DuckDB installs its extensions under HOME
        "LAGOM_LAKE_CATALOG": f"ducklake:{tmp_path / 'catalog.ducklake'}",
        "LAGOM_LAKE_DATA_PATH": f"{tmp_path / 'data'}/",
        "LAGOM_LAKE_METADATA_SCHEMA": "main",
        "LAGOM_R2_ACCESS_KEY_ID": "test",
        "LAGOM_R2_SECRET_ACCESS_KEY": "test",
        "LAGOM_R2_ENDPOINT": "https://test.invalid",
    }.items():
        monkeypatch.setenv(name, value)
    connection = attach_lake()
    for value in range(3):
        connection.execute("CREATE TABLE IF NOT EXISTS lake.main.t (v INTEGER)")
        connection.execute(f"INSERT INTO lake.main.t VALUES ({value})")
    run_maintenance(connection)
    assert connection.execute("SELECT count(*) FROM lake.main.t").fetchone() == (3,)
    connection.close()
