from __future__ import annotations

import json
from pathlib import Path

from codex_protocol_log_analyzer.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_observed_protocol.jsonl"


def test_cli_emits_machine_readable_report(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main([str(FIXTURE), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["event_count"] == 8
    assert payload["families"] == {"app-server": 3, "exec": 5}


def test_cli_strict_mode_fails_after_reporting_malformed_input(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "bad.jsonl"
    path.write_text("not-json\n", encoding="utf-8")

    assert main([str(path), "--strict"]) == 2
    assert "malformed" in capsys.readouterr().out


def test_cli_logs_unrecognized_events(tmp_path: Path) -> None:
    source = tmp_path / "rollout.jsonl"
    unknown = tmp_path / "unrecognized.jsonl"
    source.write_text(
        '{"timestamp":"2026-08-16T00:00:00Z","type":"future_state",'
        '"payload":{"value":1}}\n',
        encoding="utf-8",
    )

    assert main([str(source), "--unrecognized-out", str(unknown)]) == 0

    record = json.loads(unknown.read_text(encoding="utf-8"))
    assert record["name"] == "future_state"
    assert record["raw"]["payload"] == {"value": 1}
