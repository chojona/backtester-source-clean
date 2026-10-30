import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import platform
import sys
from .data import CSVProvider, validate
from .execution import ExecutionCosts, FillConfig
from .instruments import instrument
from .sessions import SessionCalendar
from .rolls import ContinuousSeries, RollConfig
from .intraday import IntradayEngine
from .risk import RiskConfig
from .research import ReactionConfig, WeeklyVWAPReaction, label_events, research_statistics
from .strategy import NoOrders
from .reports import write_run, serial

SCHEMA_VERSION = "1.0.0"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_snapshot():
    root = Path(__file__).parent
    files = {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob("*.py"))}
    return dict(files=files, sha256=hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest())


def read_config(path):
    config = json.loads(Path(path).read_text()) if path else {}
    if not isinstance(config, dict):
        raise ValueError("Config must be a JSON object")
    allowed = {"calendar", "features", "execution_by_symbol", "risk", "risk_by_symbol", "fills", "roll", "research", "research_by_symbol", "cash", "data_source", "input_price_basis"}
    unknown = set(config) - allowed
    if unknown:
        raise ValueError("Unknown config keys: " + ", ".join(sorted(unknown)))
    if config.get("input_price_basis", "raw") != "raw":
        raise ValueError("Executable source must contain raw constituent prices, not preadjusted continuous prices")
    return config


def objects(args, config):
    ins = instrument(args.symbol)
    calendar_config = dict(config.get("calendar", {}))
    calendar_config.setdefault("template", ins.session_template)
    if calendar_config["template"] != ins.session_template:
        raise ValueError("Session template must match instrument")
    calendar = SessionCalendar(**calendar_config)
    sidecar = args.data.parent / "metadata.json"
    if sidecar.exists() and json.loads(sidecar.read_text()).get("provider") == "Databento":
        from .providers.databento import DatabentoProvider
        if ins.symbol != "NQ" or args.interval != 1 or args.contract:
            raise ValueError("Databento normalized input requires NQ, 1-minute bars and source contract IDs")
        provider = DatabentoProvider(args.data)
        dated = provider.calendar
        if config.get("calendar") and (calendar.overrides != dated.overrides or calendar.breaks != dated.breaks):
            raise ValueError("Configured calendar disagrees with normalized dated schedule")
        return ins, dated, provider
    import csv
    with args.data.open(newline="") as stream:
        first = next(csv.DictReader(stream), {})
    if first.get("provider") == "Databento":
        raise ValueError("Databento normalized data requires its metadata.json sidecar")
    provider = CSVProvider(args.data, ins.symbol, calendar, args.interval, args.contract)
    return ins, calendar, provider


def main():
    parser = argparse.ArgumentParser(description="Point-in-time intraday futures research")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate-data", "run"):
        command = sub.add_parser(name)
        command.add_argument("data_file", nargs="?", type=Path)
        command.add_argument("--data", type=Path)
        command.add_argument("--symbol", required=True, choices=["ES", "MES", "NQ", "MNQ", "GC", "MGC"])
        command.add_argument("--contract", help="Dated contract fallback if absent in CSV")
        command.add_argument("--interval", type=int, choices=(1, 5), default=1)
        command.add_argument("--config", type=Path)
    run = sub.choices["run"]
    run.add_argument("--strategy", choices=("weekly-vwap-reaction-v1", "feature-audit"), default="weekly-vwap-reaction-v1")
    run.add_argument("--allow-missing", action="store_true")
    run.add_argument("--allow-off-tick", action="store_true")
    run.add_argument("--allow-partial-warmup", action="store_true")
    run.add_argument("--output", type=Path, default=Path("results"))
    run.add_argument("--certification-mode", choices=("exploratory", "strict"), default="exploratory")
    run.add_argument("--certification-manifest", type=Path)
    report = sub.add_parser("report")
    report.add_argument("run_id")
    report.add_argument("--output", type=Path, default=Path("results"))
    args = parser.parse_args()
    try:
        if args.command == "report":
            if Path(args.run_id).name != args.run_id:
                raise ValueError("Run ID must be a directory name, not a path")
            directory = args.output / args.run_id
            print((directory / "summary.json").read_text())
            return
        if args.data and args.data_file:
            raise ValueError("Use either positional data file or --data")
        args.data = args.data or args.data_file
        if args.data is None:
            raise ValueError("A data file is required")
        config = read_config(args.config)
        if args.command == "run":
            if args.certification_mode == "strict":
                from .market_certification import require_strict_dataset
                require_strict_dataset(args.data, args.certification_manifest,
                                       instrument=args.symbol,
                                       research="VWAP" if args.strategy == "weekly-vwap-reaction-v1" else "signal")
            elif args.certification_manifest is not None:
                raise ValueError("A certification manifest requires explicit strict mode")
        ins, calendar, provider = objects(args, config)
        input_hash = sha256(args.data)
        bars, integrity = provider.load()
        if sha256(args.data) != input_hash:
            raise ValueError("Data file changed during ingestion")
        if args.command == "validate-data":
            print(json.dumps(asdict(integrity), indent=2, default=serial))
            return
        costs = ExecutionCosts(**config.get("execution_by_symbol", {}).get(ins.symbol, {}))
        risk_options = dict(config.get("risk", {}))
        risk_options.update(config.get("risk_by_symbol", {}).get(ins.symbol, {}))
        if ins.session_template == "gold":
            risk_options.setdefault("trading_start", calendar.rth_open)
            risk_options.setdefault("trading_cutoff", calendar.rth_close)
        risk = RiskConfig(**risk_options)
        fills = FillConfig(**config.get("fills", {}))
        roll = RollConfig(**config.get("roll", {}))
        series = ContinuousSeries(calendar, roll)
        selected = tuple(series.select(bars))
        # Validate gaps in the ACTIVE series independently of inactive-contract panel gaps.
        active_integrity = validate(tuple(replace(item.raw, contract=selected[0].raw.contract) for item in selected), calendar)
        active_integrity.contracts = sorted({item.raw.contract for item in selected})
        if active_integrity.missing_intervals and not args.allow_missing:
            raise ValueError("Active series has missing intervals; inspect validate-data and explicitly use --allow-missing to retain censored observations")
        if integrity.off_tick_prices and not args.allow_off_tick:
            raise ValueError("Off-tick source prices; inspect data or explicitly use --allow-off-tick")
        research_options = dict(config.get("research", {}))
        research_options.update(config.get("research_by_symbol", {}).get(ins.symbol, {}))
        if args.allow_partial_warmup:
            research_options["require_complete_week"] = False
        reaction = ReactionConfig(**research_options)
        if any((h * 60) % selected[0].raw.duration.total_seconds() for h in reaction.horizons_minutes):
            raise ValueError("Research horizons must align to bar interval")
        if args.strategy == "weekly-vwap-reaction-v1" and reaction.level != "weekly_vwap":
            raise ValueError("Weekly research CLI requires weekly_vwap; session reaction infrastructure is available through Python API")
        snapshot = code_snapshot()
        strategy = WeeklyVWAPReaction(reaction) if args.strategy == "weekly-vwap-reaction-v1" else NoOrders()
        engine = IntradayEngine(ins, calendar, strategy, config.get("cash", 100000), costs, fills,
                                risk, config.get("features", {}), roll.position_policy).run(iter(selected))
        events = label_events(getattr(strategy, "events", []), selected, calendar, reaction, fills.ambiguity)
        statistics = research_statistics(events, reaction)
        if hasattr(provider, "sidecar_sha256") and sha256(args.data.parent / "metadata.json") != provider.sidecar_sha256:
            raise ValueError("Provider provenance changed during the run")
        if code_snapshot() != snapshot or sha256(args.data) != input_hash:
            raise ValueError("Code or data changed during the run")
        from zoneinfo import TZPATH
        timezone_path = next((Path(p) / "America/New_York" for p in TZPATH if (Path(p) / "America/New_York").is_file()), None)
        metadata = dict(schema_version=SCHEMA_VERSION, strategy=strategy.name, strategy_version=strategy.version,
            certification_mode=args.certification_mode, strict_eligible=args.certification_mode == "strict",
            parameters=strategy.parameters, instrument=asdict(ins), tick_value=ins.tick_value,
            data_file=str(args.data.resolve()), data_sha256=input_hash,
            provider_provenance=getattr(provider, "metadata", None),
            dated_calendar=calendar.provenance() if hasattr(calendar, "provenance") else None,
            data_source=config.get("data_source", "user-supplied CSV; provenance unverified"),
            timestamp_convention="UTC bar OPEN; features and events become available at bar END",
            start=selected[0].raw.timestamp, end=selected[-1].raw.end,
            interval_minutes=args.interval, config=config, calendar=asdict(calendar),
            execution_costs=asdict(costs), fill_model=asdict(fills), risk=asdict(risk),
            roll=asdict(roll), research=asdict(reaction), initial_cash=engine.portfolio.initial_cash,
            code=snapshot, python=platform.python_version(), platform=platform.platform(),
            timezone_database_file=str(timezone_path), timezone_database_sha256=sha256(timezone_path) if timezone_path else None,
            feature_config=dict(basis=engine.features.basis, ib_minutes=engine.features.ib_minutes, atr_period=engine.features.atr_period),
            drawdown_basis="after completed trades and at bar close; intrabar mark extremes not in equity curve",
            allow_missing=args.allow_missing, allow_off_tick=args.allow_off_tick,
            allow_partial_warmup=args.allow_partial_warmup,
            assumptions=["Fees and margin are illustrative unless supplied by user",
                         "Bar fills do not represent order-book queues or exact intrabar sequencing",
                         "Weekly VWAP reaction is an event study and submits no trades",
                         "Weekday session template requires dated holiday/early-close overrides",
                         "No synthetic data is presented as market history"])
        digest = hashlib.sha256(json.dumps(metadata, sort_keys=True, default=serial).encode()).hexdigest()[:12]
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + digest
        metadata["run_id"] = run_id
        metadata["created_at"] = datetime.now(timezone.utc)
        summary = write_run(args.output / run_id, metadata, engine, events, statistics,
                            series.records, dict(source=asdict(integrity), active=asdict(active_integrity)))
        print("Run: " + run_id)
        print("Events: {} | Trades: {} | Ambiguous execution bars: {}".format(
            statistics["events"], summary["total_trades"], summary["ambiguous_execution_bars"]))
        print("Results: " + str((args.output / run_id).resolve()))
        if not statistics["events"] and args.strategy == "weekly-vwap-reaction-v1":
            print("No events: check week warmup coverage, approach condition and dataset range.")
        print("Calendar: " + calendar.source)
    except (ValueError, TypeError, OSError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
