"""Content-addressed, write-once synthetic research artifacts."""

from dataclasses import asdict, fields
from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Literal, get_args, get_origin
from uuid import UUID

import pyarrow as pa
import pyarrow.parquet as pq

from .ledger import SessionRow, TradeRow


SCHEMA_VERSION = 1
INDEXED_FILES = frozenset({"manifest.json", "report.json", "trades.parquet", "sessions.parquet",
                           "events.jsonl", "selection.jsonl"})


def canonical_json(value) -> bytes:
    def encode(item):
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(f"Unsupported artifact value {type(item).__name__}")

    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
                       default=encode) + "\n").encode("utf-8")


def digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def _publish(path: Path, content: bytes) -> None:
    """Publish with an atomic exclusive link, allowing an identical concurrent retry."""
    with NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as output:
        pending = Path(output.name)
        try:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
            output.close()
            try:
                os.link(pending, path)
            except FileExistsError:
                if path.read_bytes() != content:
                    raise FileExistsError(f"Conflicting immutable artifact {path}") from None
        finally:
            output.close()
            pending.unlink()


def freeze_manifest(store: Path, plan: dict) -> Path:
    if plan.get("stage") != "synthetic" or plan.get("schema_version") != SCHEMA_VERSION or "run_id" in plan:
        raise ValueError("Expected a versioned synthetic run plan")
    run_id = "synthetic-" + digest(canonical_json(plan))
    run = store / run_id
    run.mkdir(parents=True, exist_ok=True)
    _publish(run / "manifest.json", canonical_json({**plan, "run_id": run_id}))
    return run


def _read_manifest(run: Path, content: bytes) -> dict:
    manifest = json.loads(content)
    run_id = manifest.get("run_id")
    plan = {key: value for key, value in manifest.items() if key != "run_id"}
    if (plan.get("stage") != "synthetic" or plan.get("schema_version") != SCHEMA_VERSION
            or run_id != run.name or run_id != "synthetic-" + digest(canonical_json(plan))
            or canonical_json(manifest) != content):
        raise ValueError("Invalid or misbound synthetic manifest")
    return manifest


def _ledger_schema(row_type, manifest: dict) -> pa.Schema:
    types = {date: pa.date32(), datetime: pa.timestamp("us", tz="UTC"), str: pa.string(),
             int: pa.int64(), float: pa.float64(), bool: pa.bool_()}
    columns = []
    for field in fields(row_type):
        annotation = field.type
        args = get_args(annotation)
        nullable = type(None) in args
        if nullable:
            annotation = next(arg for arg in args if arg is not type(None))
        if get_origin(annotation) is Literal:
            annotation = str
        columns.append(pa.field(field.name, types[annotation], nullable=nullable))
    protocol = manifest["protocol"]
    metadata = {"schema_version": str(SCHEMA_VERSION), "run_id": manifest["run_id"],
                "experiment_id": protocol["id"], "experiment_revision": protocol["revision"],
                "partition": "synthetic", "currency": "USD", "monetary_unit": "cent"}
    return pa.schema(columns, metadata=metadata)


def _parquet(rows, row_type, manifest: dict) -> bytes:
    table = pa.Table.from_pylist([asdict(row) for row in rows], schema=_ledger_schema(row_type, manifest))
    sink = pa.BufferOutputStream()
    # Uncompressed output avoids varying codec versions and defaults across environments.
    pq.write_table(table, sink, version="2.6", compression="NONE", use_dictionary=False)
    return sink.getvalue().to_pybytes()


def _jsonl(rows) -> bytes:
    return b"".join(canonical_json({"schema_version": SCHEMA_VERSION, **row}) for row in rows)


def publish_results(run: Path, report: dict, trades, sessions, events, selection) -> None:
    manifest_bytes = (run / "manifest.json").read_bytes()
    manifest = _read_manifest(run, manifest_bytes)
    if report.get("stage") != "synthetic" or report.get("claim_status") != "fixture_only":
        raise ValueError("Expected a synthetic fixture report")
    files = {
        "manifest.json": manifest_bytes,
        "report.json": canonical_json({**report, "schema_version": SCHEMA_VERSION, "run_id": run.name}),
        "trades.parquet": _parquet(trades, TradeRow, manifest),
        "sessions.parquet": _parquet(sessions, SessionRow, manifest),
        "events.jsonl": _jsonl(events),
        "selection.jsonl": _jsonl(selection),
    }
    for name, content in files.items():
        if name != "manifest.json":
            _publish(run / name, content)
    checksums = {name: digest(content) for name, content in files.items()}
    _publish(run / "index.json", canonical_json({"schema_version": SCHEMA_VERSION, "run_id": run.name,
                                                 "status": "complete", "sha256": checksums}))


def read_verified(run: Path) -> dict:
    if not re.fullmatch(r"synthetic-[0-9a-f]{64}", run.name) or run.is_symlink():
        raise ValueError("Expected a synthetic run directory")

    def read_local(name: str) -> bytes:
        path = run / name
        if path.is_symlink():
            raise ValueError("Synthetic run artifacts must be local files")
        return path.read_bytes()

    index = json.loads(read_local("index.json"))
    if (set(index) != {"schema_version", "run_id", "status", "sha256"}
            or index["schema_version"] != SCHEMA_VERSION or index["status"] != "complete"
            or index["run_id"] != run.name or set(index["sha256"]) != INDEXED_FILES):
        raise ValueError("Invalid artifact index")
    def checked(name: str) -> bytes:
        content = read_local(name)
        if digest(content) != index["sha256"][name]:
            raise ValueError(f"Checksum mismatch for {name}")
        return content

    manifest = _read_manifest(run, checked("manifest.json"))
    files = {name: checked(name) for name in sorted(INDEXED_FILES - {"manifest.json"})}
    for name, row_type in (("trades.parquet", TradeRow), ("sessions.parquet", SessionRow)):
        actual = pq.read_schema(pa.BufferReader(files[name]))
        if not actual.equals(_ledger_schema(row_type, manifest), check_metadata=True):
            raise ValueError(f"Unexpected ledger schema for {name}")
    for name in ("events.jsonl", "selection.jsonl"):
        for line in files[name].splitlines():
            row = json.loads(line)
            if row.get("schema_version") != SCHEMA_VERSION or row.get("run_id") != run.name:
                raise ValueError(f"Unexpected JSONL schema for {name}")
    report = json.loads(files["report.json"])
    if (report.get("schema_version") != SCHEMA_VERSION or report.get("run_id") != run.name
            or report.get("stage") != "synthetic" or report.get("claim_status") != "fixture_only"):
        raise ValueError("Invalid synthetic report")
    return report


def record_attempt(run: Path, attempt: UUID, status: str, timestamp: datetime, error_type: str | None = None) -> None:
    if (not isinstance(attempt, UUID) or not re.fullmatch(r"synthetic-[0-9a-f]{64}", run.name)
            or status not in {"started", "completed", "failed", "interrupted"}):
        raise ValueError("Invalid synthetic trial record")
    trials = run / "trials"
    trials.mkdir(exist_ok=True)
    phase = "started" if status == "started" else "finished"
    record = {"schema_version": SCHEMA_VERSION, "run_id": run.name, "attempt_id": attempt.hex,
              "status": status, "timestamp": timestamp, "error_type": error_type}
    _publish(trials / f"{attempt.hex}.{phase}.json", canonical_json(record))
