"""Run or verify the source-free H4 acceptance fixture."""

from argparse import ArgumentParser
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
from statistics import mean
import subprocess
from uuid import uuid4
from zoneinfo import TZPATH

from .artifacts import (
    SCHEMA_VERSION, canonical_json, digest, freeze_manifest, publish_results, read_verified, record_attempt,
)
from .admission import inventory_archive, inventory_pilot
from .custody import evaluate_locked, prepare_rehearsal
from .evaluation import evaluate
from .inputs import acceptance_fixture
from .ledger import pair_session, scenarios
from .protocol import load_registry
from .rules import detect_opening_range
from .validation import synthetic_validation


def _code_provenance() -> dict:
    package = Path(__file__).resolve().parent
    root = package.parent.parent
    files = (*sorted(package.glob("*.py")), package.parent / "data.py", package.parent / "instruments.py")
    hashes = {path.relative_to(root).as_posix(): digest(path.read_bytes()) for path in files}
    commit = None
    if (root / ".git").exists():
        try:
            commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                             text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    return {"git_head": commit, "source_sha256": digest(canonical_json(hashes)), "files": hashes}


def _environment(zone: str) -> dict:
    zonefile = next((Path(root) / zone for root in TZPATH if (Path(root) / zone).is_file()), None)
    try:
        tzdata = version("tzdata")
    except PackageNotFoundError:
        tzdata = None
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "pyarrow": version("pyarrow"), "zoneinfo_sha256": digest(zonefile.read_bytes()) if zonefile else None,
            "tzdata": tzdata}


def _source_record(session) -> dict:
    bars = [
        {"label": label, "available_at": observation.available_at,
         "ohlcv": [observation.bar.open, observation.bar.high, observation.bar.low,
                   observation.bar.close, observation.bar.volume],
         "traded": observation.traded}
        for label, observation in sorted(session.observations.items())
    ]
    return {"day": session.day, "contract": session.contract, "cash_open": session.cash_open,
            "cash_close": session.cash_close, "fixture_sha256": digest(canonical_json(bars)),
            "fixture_bars": len(bars), "coverage_reason": session.coverage_reason()}


def run_synthetic(protocol_path: Path, store: Path) -> Path:
    registry = load_registry(protocol_path)
    protocol = registry.get("H4", "1.0.0")
    fixture = acceptance_fixture(protocol)
    cost_grid = scenarios(protocol)
    source_records = [_source_record(session) for session in fixture]
    run = freeze_manifest(store, {
        "schema_version": SCHEMA_VERSION, "stage": "synthetic", "data_lane": "constructed_h4_acceptance_v1",
        "protocol": asdict(protocol), "family": registry.family, "registry_schema_version": registry.schema_version,
        "definition_sha256": registry.source_sha256, "scenarios": [asdict(scenario) for scenario in cost_grid],
        "code": _code_provenance(), "environment": _environment(protocol.timezone),
        "cash_calendar": source_records, "holdout_policy": "disabled",
        "execution": "exact scheduled open, first-recorded trade proxy, close/open equality allowed",
        "availability": "constructed completed-bar availability with explicit timestamp per bar",
        "pairing": "exclude both arms from the estimand if any required input or fill is unavailable",
        "fee_provenance": "provisional synthetic round-trip fee",
        "inference": "circular stationary session bootstrap, percentile CI, centered upper tail with add-one",
        "multiplicity": "synthetic demonstration of ten-slot Holm with untested inputs set to one",
    })
    attempt = uuid4()
    record_attempt(run, attempt, "started", datetime.now(timezone.utc))
    try:
        trades, sessions, events, selection = [], [], [], []
        for session, source in zip(fixture, source_records, strict=True):
            decision = detect_opening_range(session, protocol)
            events.append({"run_id": run.name, "day": session.day, "contract": session.contract,
                           "decision": asdict(decision), "fixture_sha256": source["fixture_sha256"],
                           "availability_provenance": "constructed"})
            selection.append({"run_id": run.name, **source, "selection": "constructed_fixed_contract"})
            for scenario in cost_grid:
                session_row, trade_rows = pair_session(session, protocol, decision, scenario,
                                                       coverage_reason=source["coverage_reason"])
                sessions.append(session_row)
                trades.extend(trade_rows)
        report = evaluate(sessions, protocol)
        report["scenario_summaries"] = {}
        for scenario in cost_grid:
            eligible = [row for row in sessions if row.scenario_id == scenario.id and row.eligible]
            report["scenario_summaries"][scenario.id] = {
                "eligible_sessions": len(eligible),
                "candidate_filled_sessions": sum(row.candidate_status == "filled" for row in eligible),
                "benchmark_filled_sessions": sum(row.benchmark_status == "filled" for row in eligible),
                "means_cents": {
                    field: mean(getattr(row, field) for row in eligible) if eligible else None
                    for field in ("candidate_gross_cents", "benchmark_gross_cents", "candidate_net_cents",
                                  "benchmark_net_cents", "uplift_cents")
                },
            }
        publish_results(run, report, trades, sessions, events, selection)
        read_verified(run)
    except BaseException as error:
        status = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        record_attempt(run, attempt, status, datetime.now(timezone.utc), type(error).__name__)
        raise
    record_attempt(run, attempt, "completed", datetime.now(timezone.utc))
    return run


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    synthetic = commands.add_parser("synthetic", help="Run the built-in H4 fixture")
    synthetic.add_argument("--protocol", required=True, type=Path)
    synthetic.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser("verify", help="Verify a completed synthetic run")
    verify.add_argument("run_directory", type=Path)
    prepare = commands.add_parser("prepare-rehearsal", help="Freeze the built-in synthetic holdout plan")
    prepare.add_argument("store", type=Path)
    rehearsal = commands.add_parser("evaluate-rehearsal", help="Consume a prepared synthetic holdout once")
    rehearsal.add_argument("store", type=Path)
    rehearsal.add_argument("--confirm-binding", required=True)
    inventory = commands.add_parser("inventory-pilot", help="Inventory the 2023 pilot evidence without decoding bars")
    inventory.add_argument("evidence_root", type=Path)
    archive = commands.add_parser("inventory-archive", help="Inventory outright archive and terminal coverage metadata")
    archive.add_argument("evidence_root", type=Path)
    commands.add_parser("validate-synthetic", help="Run constructed bootstrap, power and SPA checks")
    args = parser.parse_args()
    if args.command == "synthetic":
        print(run_synthetic(args.protocol, args.output).resolve())
    elif args.command == "verify":
        report = read_verified(args.run_directory)
        print(f"{report['run_id']} verified ({report['eligible_sessions']} eligible synthetic sessions)")
    elif args.command == "prepare-rehearsal":
        print(prepare_rehearsal(args.store))
    elif args.command == "evaluate-rehearsal":
        report = evaluate_locked(args.store, stage="synthetic", confirmation=args.confirm_binding)
        print(canonical_json(report).decode(), end="")
    elif args.command == "inventory-pilot":
        print(json.dumps(inventory_pilot(args.evidence_root), indent=2))
    elif args.command == "inventory-archive":
        print(json.dumps(inventory_archive(args.evidence_root), indent=2))
    else:
        print(json.dumps(synthetic_validation(), indent=2))


if __name__ == "__main__":
    main()
