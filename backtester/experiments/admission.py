"""Read-only inventory of the documented outright archive and Phase 2 pilot."""

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from hashlib import file_digest
import json
from pathlib import Path
import re

import pyarrow.parquet as pq


RAW = Path("data/raw/databento/NQ")
PILOT = RAW / "phase2-2023-exploratory-pilot-v1.0.0"
CONTINUATION = RAW / "phase2-2023-pilot-continuation-v1.0.0"
CONTINUATION_REVIEW = Path("reports/nq-phase2-2023-pilot-continuation-execution-v1.0.0")
CALENDAR = Path("calendars/nq-history-v3.json")
CALENDAR_REVIEW = Path("reports/nq-phase2-2023-calendar-v1.1.0/summary.json")
JAN3_START = datetime(2023, 1, 2, 23, tzinfo=timezone.utc)
JAN3_END = datetime(2023, 1, 3, 22, tzinfo=timezone.utc)
CLEAN = Path("results/nq-ohlcv-clean-v1/cleaned")
TERMINAL = Path("results/nq-ohlcv-research-v2/build")
COMPLETENESS = Path("results/nq-ohlcv-completeness-v2/final/summary.json")


def _scoped(root: Path, relative: Path) -> Path:
    path = root / relative
    if path.resolve() != path or path.is_symlink():
        raise ValueError("Inventory paths must be direct, within the pilot package")
    return path


def _metadata(root: Path, relative: Path):
    path = _scoped(root, relative)
    if not path.is_file():
        return None

    def unique_fields(pairs):
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError("Duplicate inventory metadata field")
        return fields

    return json.loads(path.read_bytes(), object_pairs_hook=unique_fields)


def _artifact(root: Path, relative: Path, declared_hash: str | None) -> str:
    path = _scoped(root, relative)
    if not path.is_file():
        return "missing"
    if type(declared_hash) is not str or not re.fullmatch(r"[0-9a-f]{64}", declared_hash):
        return "unbound"
    with path.open("rb") as stream:
        return "matches_ledger" if file_digest(stream, "sha256").hexdigest() == declared_hash else "mismatch"


def _request(root: Path, ledger: dict | None, number_field: str, number: int,
             schema: str, raw: Path | None) -> dict:
    if ledger is None:
        return {"schema": schema, "status": "ledger_missing"}
    matches = [item for item in ledger["requests"] if item.get(number_field) == number]
    if len(matches) != 1:
        raise ValueError("Expected one ledger row for the fixed pilot request")
    entry = matches[0]
    request, metadata = entry["request"], entry.get("metadata") or {}
    symbols = tuple(request["symbols"])
    start, end = (datetime.fromisoformat(request[bound]) for bound in ("start", "end"))
    if (request["dataset"] != "GLBX.MDP3" or request["schema"] != schema
            or request["stype_in"] != "raw_symbol" or not symbols or len(set(symbols)) != len(symbols)
            or any(not re.fullmatch(r"NQ[HMUZ][0-9]{1,2}", symbol) for symbol in symbols)
            or start.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0)
            or not datetime(2020, 1, 1, tzinfo=timezone.utc) <= start < end
            <= JAN3_END + timedelta(minutes=45)
            or (schema != "definition" and (start != JAN3_START or end < JAN3_END))):
        raise ValueError("Ledger request falls outside the supported pilot scope")
    count = entry.get("record_count")
    if count is not None and (type(count) is not int or count < 0):
        raise ValueError("Invalid ledger record count")
    if metadata and (metadata["dataset"] != request["dataset"] or metadata["schema"] != schema
                     or tuple(metadata["symbols"]) != symbols or metadata["stype_in"] != "raw_symbol"
                     or metadata["start"] != int(start.timestamp()) * 10**9
                     or metadata["end"] != int(end.timestamp()) * 10**9):
        raise ValueError("Response metadata differs from the fixed pilot request")
    per_symbol = entry.get("counts_by_symbol") or {}
    if per_symbol and (set(per_symbol) != set(symbols) or sum(per_symbol.values()) != count
                       or any(type(n) is not int or n < 0 for n in per_symbol.values())):
        raise ValueError("Inconsistent contract counts in the pilot ledger")
    return {
        "provider": "Databento", "dataset": request["dataset"], "schema": schema,
        "start_utc": start.isoformat(), "end_utc": end.isoformat(), "requested_contracts": symbols,
        "mapped_contracts": tuple(sorted(set(symbols) & metadata.get("mappings", {}).keys())),
        "partial_contracts": tuple(sorted(set(symbols) & set(metadata.get("partial", ())))),
        "unresolved_contracts": tuple(sorted(set(symbols) & set(metadata.get("not_found", ())))),
        "status": entry["state"], "declared_records": count, "declared_records_by_contract": per_symbol,
        "raw_integrity": _artifact(root, raw, entry.get("raw_sha256")) if raw else "out_of_scope",
    }


def inventory_pilot(root: Path) -> dict:
    """Inspect fixed documentary paths and hash fixed raw artifacts without decoding rows."""
    root = root.resolve(strict=True)
    original = _metadata(root, PILOT / "acquisition-ledger.json")
    resumed = _metadata(root, CONTINUATION_REVIEW / "acquisition-ledger.json")
    calendar = _metadata(root, CALENDAR)
    review = _metadata(root, CALENDAR_REVIEW)
    requests = [
        _request(root, original, "request_number", 1, "definition", PILOT / "01-definition.dbn.zst"),
        _request(root, resumed, "original_request_number", 2, "ohlcv-1m", CONTINUATION / "02-ohlcv-1m.dbn.zst"),
        _request(root, resumed, "original_request_number", 3, "trades", None),
        _request(root, resumed, "original_request_number", 4, "status", None),
    ]
    calendar_inventory = {"scope_includes_pilot_date": None, "declared_status": None}
    if calendar is not None:
        scope = calendar["scope"]
        first, last = (date.fromisoformat(scope[key]) for key in ("first_trading_date", "last_trading_date"))
        calendar_inventory.update(scope_includes_pilot_date=first <= JAN3_END.date() <= last,
                                  declared_status=calendar["status"])
    if review is not None:
        calendar_inventory.update({key: review[key] for key in (
            "calendar_reconciliation", "calendar_question_minutes_remaining", "feed_gap_minutes_separate",
            "calendar_question_dates", "unobserved_weekday_candidates_still_unverified",
            "effective_dated_2023_NQ_holiday_product_rows_recovered",
        )})
    return {
        "schema_version": 1, "scope": "documented_2023_pilot", "admission": "NO-GO",
        "calendar": calendar_inventory, "requests": requests,
        "sample_counts": {"pilot_target_sessions": 1, "eligible_sessions_established": 0,
                          "actual_eligible_sessions": None},
        "unresolved_evidence": (
            "Independent dated contract roster and instrument identity reconciliation",
            "Dated exchange session boundaries, exceptions and calendar authority",
            "Date-specific bar coverage, observed trades, status and gap attribution",
            "Original publication, receipt, revision and ingestion timing",
            "Frozen admitted session counts, exposure exclusions and custody authority",
        ),
    }


def _sealed_members(root: Path, directory: Path, key: str, names: tuple[str, ...]) -> dict:
    seal = _metadata(root, directory / "SUCCESS.json") or {}
    hashes = seal.get(key, {})
    return {name: _artifact(root, directory / name, hashes.get(name)) for name in names}


def _clean_archive(root: Path) -> dict:
    bars = "nq-ohlcv-1m.parquet"
    sidecars = ("row-provenance.parquet", "session-labels.parquet", "coverage.parquet")
    seals = _sealed_members(root, CLEAN, "output_sha256", (bars, *sidecars, "contracts.json", "request-scopes.json"))
    result = {"integrity": seals}
    if any(status != "matches_ledger" for status in seals.values()):
        return result

    # Footer schema and row counts only for the tables carrying market rows.
    with pq.ParquetFile(_scoped(root, CLEAN / bars)) as parquet:
        mandatory = {"timestamp_utc", "contract", "open", "high", "low", "close", "volume"}
        if not mandatory.issubset(parquet.schema_arrow.names):
            raise ValueError("Outright archive does not have the expected raw bar schema")
        result["bar_rows"] = parquet.metadata.num_rows
        result["bar_columns"] = parquet.schema_arrow.names
    records = {}
    for name in sidecars:
        with pq.ParquetFile(_scoped(root, CLEAN / name)) as parquet:
            records[name] = parquet.metadata.num_rows
    contracts = _metadata(root, CLEAN / "contracts.json")
    scopes = _metadata(root, CLEAN / "request-scopes.json")
    roster = sorted(item["contract"] for item in contracts)
    if (not roster or len(set(roster)) != len(roster)
            or any(not re.fullmatch(r"NQ[HMUZ][0-9]{1,2}", contract) for contract in roster)
            or any(type(item["rows"]) is not int or item["rows"] <= 0 for item in contracts)
            or sum(item["rows"] for item in contracts) != result["bar_rows"]
            or records["session-labels.parquet"] != result["bar_rows"]):
        raise ValueError("Archive contract counts or session labels do not reconcile to the bar footer")
    first = min(datetime.fromisoformat(row["first_utc"]) for row in contracts).astimezone(timezone.utc)
    last = max(datetime.fromisoformat(row["last_utc"]) for row in contracts).astimezone(timezone.utc)
    result.update(sidecar_rows=records, observed_roster=roster,
                  first_bar_utc=first.isoformat(), last_bar_utc=last.isoformat(),
                  request_scopes=len(scopes), requested_roster=sorted({row["contract"] for row in scopes}),
                  source_ids=len({row["source_id"] for row in scopes}))
    return result


def _terminal_availability(root: Path) -> dict:
    name = "session-eligibility.parquet"
    seals = _sealed_members(root, TERMINAL, "outputs", (name, "summary.json"))
    result = {"integrity": seals}
    if any(status != "matches_ledger" for status in seals.values()):
        return result

    with pq.ParquetFile(_scoped(root, TERMINAL / name)) as parquet:
        rows = parquet.read(columns=["trading_date", "eligible_full_session"]).to_pylist()
    dates = [date.fromisoformat(str(row["trading_date"])) for row in rows]
    summary = _metadata(root, TERMINAL / "summary.json")
    by_year = Counter(day.year for day, row in zip(dates, rows, strict=True) if row["eligible_full_session"] is True)
    if (len(set(dates)) != len(dates) or any(type(row["eligible_full_session"]) is not bool for row in rows)
            or len(dates) != summary["candidate_sessions"] or by_year.total() != summary["eligible_sessions"]):
        raise ValueError("Terminal coverage counts do not reconcile to its sealed summary")
    result.update(candidate_sessions=len(dates), full_grid_sessions=by_year.total(), full_grid_by_year=dict(by_year),
                  policy="terminal_fixed_roll_retrospective_qc")
    return result


def inventory_archive(root: Path) -> dict:
    """Reconcile archive provenance and retrospective availability without evaluating rules."""
    root = root.resolve(strict=True)
    clean = _clean_archive(root)
    terminal = _terminal_availability(root)
    calendar = _metadata(root, Path("backtester") / CALENDAR)
    review = _metadata(root, COMPLETENESS)
    return {
        "schema_version": 1, "scope": "documented_nq_outright_archive", "admission": "NO-GO",
        "outright_archive": clean, "terminal_coverage_reference": terminal,
        "calendar": ({key: calendar[key] for key in ("version", "scope", "timezone", "status")}
                     if calendar else None),
        "completeness_review": ({key: review[key] for key in ("all_requested_contracts",
                                  "calendar_candidates_unresolved", "boundary_observations_unresolved")}
                                if review else None),
        "sample_counts": {"historical_sessions_established": 0, "eligible_sessions_under_proposed_selector": None},
        "unresolved_evidence": (
            "Effective-dated point-in-time outright roster, expiry and prior-Globex volume for every candidate",
            "Dated exchange and cash-grid exception coverage and unresolved minute attribution",
            "Original final-bar publication, receipt, revision and strategy ingestion",
            "Approved selector and session exposure register, chronological development and holdout counts",
            "Cost and next-open proxy authority, independent protocol and custody approvals",
        ),
    }
