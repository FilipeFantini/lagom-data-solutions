import pytest

import pipeline
from conftest import NOW


def test_naive_timestamp_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        pipeline.main(["--since", "2026-10-16T00:00:00", "--until", "2026-10-16T01:00:00Z"], NOW)

    assert exit_info.value.code == 2
    assert "has no UTC offset" in capsys.readouterr().err
