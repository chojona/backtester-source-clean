from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from backtester.experiments import artifacts
from backtester.experiments.__main__ import run_synthetic
from backtester.experiments.artifacts import INDEXED_FILES, canonical_json, digest, read_verified


DEFINITION = Path(__file__).resolve().parents[1] / "config/experiments/h4.synthetic.v1.toml"


def test_artifacts_round_trip_and_concurrent_identical_publication(tmp_path):
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(lambda _: run_synthetic(DEFINITION, tmp_path), range(2))
    assert first == second
    assert not list(first.glob(".pending-*"))
    manifest = json.loads((first / "manifest.json").read_bytes())
    assert manifest["holdout_policy"] == "disabled"
    assert all("\\" not in path for path in manifest["code"]["files"])
    report = read_verified(first)
    assert (report["calendar_sessions"], report["eligible_sessions"]) == (5, 4)
    assert report["scenario_summaries"]["base"]["means_cents"]["uplift_cents"] == 1625
    assert sum(entry["status"] == "untested" for entry in report["family"]) == 9
    assert len(list((first / "trials").glob("*.finished.json"))) == 2
    snapshot = {name: (first / name).read_bytes() for name in INDEXED_FILES | {"index.json"}}
    assert first == run_synthetic(DEFINITION, tmp_path)
    assert all((first / name).read_bytes() == content for name, content in snapshot.items())

    trades = pq.read_table(first / "trades.parquet")
    sessions = pq.read_table(first / "sessions.parquet")
    assert (trades.num_rows, sessions.num_rows) == (100, 50)
    assert trades.schema.metadata[b"run_id"].decode() == first.name
    assert trades.schema.metadata[b"monetary_unit"] == b"cent"
    legs = {(row["day"], row["scenario_id"], row["arm"]): row for row in trades.to_pylist()}
    for row in sessions.to_pylist():
        if row["eligible"]:
            key = (row["day"], row["scenario_id"])
            candidate = legs[*key, "candidate"]
            benchmark = legs[*key, "benchmark"]
            assert row["uplift_cents"] == candidate["net_cents"] - benchmark["net_cents"]

    path = first / "report.json"
    path.write_bytes(snapshot["report.json"] + b" ")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        read_verified(first)
    with pytest.raises(FileExistsError, match="Conflicting immutable artifact"):
        run_synthetic(DEFINITION, tmp_path)
    assert path.read_bytes() == snapshot["report.json"] + b" "


def test_incomplete_write_is_unreadable_and_retry_resumes(tmp_path, monkeypatch):
    publish = artifacts._publish

    def fail_at_commit_marker(path, content):
        if path.name == "index.json":
            raise OSError("simulated interrupted publication")
        publish(path, content)

    with monkeypatch.context() as patch:
        patch.setattr(artifacts, "_publish", fail_at_commit_marker)
        with pytest.raises(OSError, match="interrupted publication"):
            run_synthetic(DEFINITION, tmp_path)
    run, = tmp_path.iterdir()
    with pytest.raises(FileNotFoundError):
        read_verified(run)
    failed, = (run / "trials").glob("*.finished.json")
    assert json.loads(failed.read_bytes())["status"] == "failed"
    assert run == run_synthetic(DEFINITION, tmp_path)
    assert read_verified(run)["stage"] == "synthetic"

    # A checksummed file still has to match the schema for its declared role.
    index_path = run / "index.json"
    index = json.loads(index_path.read_bytes())
    wrong_schema = (run / "trades.parquet").read_bytes()
    (run / "sessions.parquet").write_bytes(wrong_schema)
    index["sha256"]["sessions.parquet"] = digest(wrong_schema)
    index_path.write_bytes(canonical_json(index))
    with pytest.raises(ValueError, match="Unexpected ledger schema"):
        read_verified(run)
