from hashlib import sha256
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backtester.experiments.admission import (
    CALENDAR, CLEAN, CONTINUATION, CONTINUATION_REVIEW, PILOT, TERMINAL, inventory_archive, inventory_pilot,
)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_inventory_fixed_scope_and_zero_records_are_unresolved(tmp_path):
    raw = CONTINUATION / "02-ohlcv-1m.dbn.zst"
    fixture = b"Opaque test bytes, never decoded"
    path = tmp_path / raw
    path.parent.mkdir(parents=True)
    path.write_bytes(fixture)
    rows = []
    for number, schema in enumerate(("ohlcv-1m", "trades", "status"), start=2):
        rows.append({"original_request_number": number, "state": "NOT_STARTED", "record_count": None,
                     "request": {"dataset": "GLBX.MDP3", "schema": schema, "stype_in": "raw_symbol",
                                 "symbols": ["NQH3"], "start": "2023-01-02T23:00:00Z",
                                 "end": "2023-01-03T22:00:00Z"}})
    rows[0].update(state="ZERO_RECORD_RESPONSE — COVERAGE_UNRESOLVED", record_count=0,
                   counts_by_symbol={"NQH3": 0}, raw_path="../../../sealed/outcomes.parquet",
                   raw_sha256=sha256(fixture).hexdigest())
    ledger_path = tmp_path / CONTINUATION_REVIEW / "acquisition-ledger.json"
    write_json(ledger_path, {"requests": rows})
    write_json(tmp_path / CALENDAR, {"scope": {"first_trading_date": "2022-01-01",
                                               "last_trading_date": "2024-01-01"}, "status": "incomplete"})
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    (sealed / "outcomes.parquet").write_bytes(b"Must stay outside inventory")
    snapshot = {file: file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()}
    result = inventory_pilot(tmp_path)
    assert result["admission"] == "NO-GO"
    assert result["requests"][0]["status"] == "ledger_missing"
    assert result["requests"][1]["raw_integrity"] == "matches_ledger"
    assert result["requests"][1]["declared_records"] == 0
    assert result["requests"][1]["declared_records_by_contract"] == {"NQH3": 0}
    assert result["requests"][2]["declared_records"] is None
    assert result["calendar"]["scope_includes_pilot_date"] is True
    assert result["sample_counts"] == {"pilot_target_sessions": 1, "eligible_sessions_established": 0,
                                       "actual_eligible_sessions": None}
    assert snapshot == {file: file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()}
    path.write_bytes(b"modified")
    assert inventory_pilot(tmp_path)["requests"][1]["raw_integrity"] == "mismatch"
    rows[0]["request"]["end"] = "2025-01-03T22:00:00Z"
    write_json(ledger_path, {"requests": rows})
    with pytest.raises(ValueError, match="outside the supported pilot scope"):
        inventory_pilot(tmp_path)


def test_inventory_reports_absent_package_and_refuses_duplicate_metadata(tmp_path):
    assert all(row["status"] == "ledger_missing" for row in inventory_pilot(tmp_path)["requests"])
    ledger = tmp_path / PILOT / "acquisition-ledger.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"requests": [], "requests": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        inventory_pilot(tmp_path)


def test_archive_uses_footer_and_projects_only_coverage_fields(tmp_path, monkeypatch):
    clean, terminal = tmp_path / CLEAN, tmp_path / TERMINAL
    clean.mkdir(parents=True)
    terminal.mkdir(parents=True)
    bars = "nq-ohlcv-1m.parquet"
    coverage = "session-eligibility.parquet"
    pq.write_table(pa.table({"timestamp_utc": ["2023-01-03T14:30:00Z"], "contract": ["NQH3"],
                             "open": [999999], "high": [999999], "low": [999999], "close": [999999],
                             "volume": [1]}), clean / bars)
    for name in ("row-provenance.parquet", "session-labels.parquet", "coverage.parquet"):
        pq.write_table(pa.table({"metadata_only": [True]}), clean / name)
    write_json(clean / "contracts.json", [{"contract": "NQH3", "first_utc": "2023-01-03T14:30:00Z",
                                           "last_utc": "2023-01-03T14:30:00Z", "rows": 1}])
    write_json(clean / "request-scopes.json", [{"contract": "NQH3", "source_id": "constructed"}])
    pq.write_table(pa.table({"trading_date": ["2023-01-03", "2023-01-04"], "eligible_full_session": [True, False],
                             "outcome_sentinel": [999999, 999999]}), terminal / coverage)
    write_json(terminal / "summary.json", {"candidate_sessions": 2, "eligible_sessions": 1})

    def seal(directory, key):
        write_json(directory / "SUCCESS.json", {key: {path.name: sha256(path.read_bytes()).hexdigest()
                                                     for path in directory.iterdir() if path.name != "SUCCESS.json"}})

    seal(clean, "output_sha256")
    seal(terminal, "outputs")
    original_read = pq.ParquetFile.read
    read_calls = []

    def read_projection(self, *, columns):
        assert columns == ["trading_date", "eligible_full_session"]
        read_calls.append(columns)
        return original_read(self, columns=columns)

    monkeypatch.setattr(pq.ParquetFile, "read", read_projection)
    result = inventory_archive(tmp_path)
    assert len(read_calls) == 1
    assert result["outright_archive"]["bar_rows"] == 1
    assert result["outright_archive"]["observed_roster"] == ["NQH3"]
    assert result["terminal_coverage_reference"]["full_grid_by_year"] == {2023: 1}
    assert result["sample_counts"]["eligible_sessions_under_proposed_selector"] is None
    assert "999999" not in json.dumps(result)
    write_json(terminal / "summary.json", {"candidate_sessions": 2, "eligible_sessions": 2})
    assert "full_grid_sessions" not in inventory_archive(tmp_path)["terminal_coverage_reference"]
    seal(terminal, "outputs")
    with pytest.raises(ValueError, match="counts do not reconcile"):
        inventory_archive(tmp_path)
