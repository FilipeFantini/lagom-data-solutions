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
