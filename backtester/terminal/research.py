"""Versioned causal VWAP events; outcomes are computed in a separate pass."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import mean

from backtester.features import VWAP
from backtester.sessions import NY, local_at
from backtester.signal_evaluation import _simultaneous_interval
from backtester.research_nq.adapter import ReadOnlyExploratoryAdapter

SPEC = {
    "id": "vwap-acceptance-rejection", "version": "1.0.0",
    "basis": "OHLCV typical price proxy, not trade-notional VWAP",
    "reset": "exchange session open (18:00 ET previous day)",
    "signal_window_et": ["09:45", "12:00"], "confirmation": "bar close",
    "acceptance": "previous close crosses VWAP; next close remains on same side; both distances >= 0.25 points",
    "rejection": "previous close on one side; current range touches current VWAP and close returns >= 0.25 points to that side",
    "priority": "acceptance before rejection", "cooldown_minutes": 15,
    "horizons_minutes": [5, 10, 15], "bootstrap_seed": 1701,
    "bootstrap_replications": 500, "minimum_ci_sessions": 5,
    "cost_scenario": {"entry": "first bar open strictly after confirmation", "exit": "open 15 minutes after scenario entry",
                      "point_value_usd": 20, "slippage_points_per_side": 0.25, "commission_usd_per_side": 2.5},
    "baseline": "same ET minute, direction, and partition on other eligible sessions; includes event sessions at other dates",
    "inference": "descriptive research; no proven alpha; no parameter search",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Explicit timezone required")
    return result.astimezone(timezone.utc)


def code_version():
    root = Path(__file__).parents[2]
    files = []
    for source in (root / "backtester", root / "terminal"):
        for directory, dirs, names in os.walk(source):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__", "test-results", "playwright-report"})
            files.extend(Path(directory) / n for n in names if n != "next-env.d.ts" and Path(n).suffix in {".py", ".js", ".html", ".ts", ".tsx", ".css", ".mjs"})
    return digest({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)})


def eligible_sessions(adapter, partitions, start, end):
    """Reject partial/gapped sessions, rather than resetting VWAP after a gap."""
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if start > end or (end - start).days > 366:
        raise ValueError("Choose an ordered range of at most 367 calendar dates")
    selected = [day for day in sorted(partitions) if start <= date.fromisoformat(day) <= end]
    if not selected:
        raise ValueError("No declared sessions in selected range")
    if any(partitions[day] == "final_holdout" for day in selected):
        raise ValueError("Final holdout is sealed; research and chart access blocked")
    if any(partitions[day] not in {"development", "validation"} for day in selected):
        raise ValueError("Unrecognized chronological partition")
    groups = defaultdict(list)
    records = tuple(adapter.iter_records(datetime.max.replace(tzinfo=timezone.utc)))
    for record in records:
        info = adapter.calendar.classify(record.bar.timestamp)
        if info and info.trading_date.isoformat() in selected:
            groups[info.trading_date.isoformat()].append(record)
    accepted, excluded = {}, {}
    for day in selected:
        opened = adapter.calendar.bounds(date.fromisoformat(day))[0]
        until = local_at(date.fromisoformat(day), "12:17")
        rows = [r for r in groups[day] if opened <= r.bar.timestamp < until]
        expected = []
        t = opened
        while t < until:
            if adapter.calendar.valid_bar(t, timedelta(minutes=1)):
                expected.append(t)
            t += timedelta(minutes=1)
        try:
            if not expected or [r.bar.timestamp for r in rows] != expected:
                raise ValueError("incomplete, duplicate, unordered or off-grid session")
            if any(r.bar.duration != timedelta(minutes=1) or r.bar.volume <= 0 or
                   any(not math.isfinite(x) for x in (r.bar.open, r.bar.high, r.bar.low, r.bar.close, r.bar.volume))
                   for r in rows):
                raise ValueError("requires finite positive-volume one-minute observations")
            # Reuse the adapter's calendar/grid/classification and availability controls,
            # one calendar segment at a time (adapter rejects mixed segments).
            segments = defaultdict(list)
            for r in rows:
                segments[adapter.calendar.classify(r.bar.timestamp).session].append(r)
                if r.available_at > r.bar.end:
                    raise ValueError("publication after close; bar-close confirmation unavailable")
            for segment in segments.values():
                adapter.require_complete_observations(segment[-1].bar.end,
                    start_utc=segment[0].bar.timestamp, end_utc=segment[-1].bar.end)
            accepted[day] = [r.bar for r in rows]
        except ValueError as error:
            excluded[day] = str(error)
    if not accepted:
        raise ValueError("No eligible complete sessions: " + canonical(excluded))
    return accepted, excluded


def detect(bars):
    """Prefix invariant: only current and previous completed observations used."""
    vwap, previous, previous_distance = VWAP("typical"), None, None
    values, events, last = [], [], None
    for i, bar in enumerate(bars):
        value = vwap.update(bar)
        values.append(value)
        distance = bar.close - value
        local = bar.end.astimezone(NY).strftime("%H:%M")
        direction, classification = 0, None
        if previous is not None and "09:45" <= local <= "12:00":
            # A crossing at previous close, followed by one completed holding bar.
            if i >= 2:
                before = bars[i - 2].close - values[i - 2]
                if before <= 0 and previous_distance >= .25 and distance >= .25:
                    direction, classification = 1, "acceptance"
                elif before >= 0 and previous_distance <= -.25 and distance <= -.25:
                    direction, classification = -1, "acceptance"
            if classification is None:
                if previous_distance >= .25 and bar.low <= value and distance >= .25:
                    direction, classification = 1, "rejection"
                elif previous_distance <= -.25 and bar.high >= value and distance <= -.25:
                    direction, classification = -1, "rejection"
        if direction and (last is None or bar.end - last >= timedelta(minutes=15)):
            events.append({"bar_index": i, "bar_time": stamp(bar.timestamp),
                "signal_at": stamp(bar.end), "contract": bar.contract,
                "direction": direction, "classification": classification,
                "vwap": value, "reference_close": bar.close})
            last = bar.end
        previous, previous_distance = bar, distance
    return values, events


def label(bars, index, direction):
    result = {}
    for horizon in SPEC["horizons_minutes"]:
        future = bars[index + 1:index + horizon + 1]
        if len(future) != horizon:
            raise ValueError("Incomplete forward evaluation window")
        reference = bars[index].close
        moves = [(b.high - reference) * direction for b in future] + [(b.low - reference) * direction for b in future]
        result[str(horizon)] = {"outcome_at": stamp(future[-1].end),
            "signed_return": direction * (future[-1].close / reference - 1),
            "signed_points": direction * (future[-1].close - reference),
            "mfe_points": max(0, max(moves)), "mae_points": min(0, min(moves))}
    # A cost sensitivity scenario, NOT a portfolio simulation. Opening exactly at
    # confirmation is excluded; no same-close or ambiguous boundary fill.
    entry, exit_bar = bars[index + 2], bars[index + 17]
    if entry.timestamp <= bars[index].end or exit_bar.timestamp - entry.timestamp != timedelta(minutes=15):
        raise ValueError("Scenario timing is invalid")
    gross = direction * (exit_bar.open - entry.open) * 20
    result["cost_scenario"] = {"entry_at": stamp(entry.timestamp), "exit_at": stamp(exit_bar.timestamp),
        "entry_price": entry.open + direction * .25, "exit_price": exit_bar.open - direction * .25,
        "gross_usd": gross, "cost_usd": 15.0, "net_usd": gross - 15.0,
        "classification": "independent hypothetical event; not an actual simulated strategy trade"}
    return result


def summarize(events):
    summaries = []
    # Bonferroni across all reported intervals (2 partitions x 3 horizons x 3 metrics).
    alpha = .05 / 18
    for partition in ("development", "validation"):
        subset = [e for e in events if e["partition"] == partition]
        for h in map(str, SPEC["horizons_minutes"]):
            def interval(field):
                groups = defaultdict(list)
                for e in subset:
                    groups[e["session"]].append(field(e))
                return _simultaneous_interval(groups, alpha, 1701, 500)
            def average(field):
                return mean(field(e) for e in subset) if subset else None
            summaries.append({"partition": partition, "horizon_minutes": int(h),
                "event_count": len(subset), "session_count": len({e["session"] for e in subset}),
                "directional_hit_rate": average(lambda e: float(e["outcomes"][h]["signed_return"] > 0)),
                "hit_rate_ci": interval(lambda e: float(e["outcomes"][h]["signed_return"] > 0)),
                "mean_signed_return": average(lambda e: e["outcomes"][h]["signed_return"]),
                "return_ci": interval(lambda e: e["outcomes"][h]["signed_return"]),
                "mean_mfe_points": average(lambda e: e["outcomes"][h]["mfe_points"]),
                "mean_mae_points": average(lambda e: e["outcomes"][h]["mae_points"]),
                "matched_baseline_return": average(lambda e: e["baseline"][h]) if subset and all(e["baseline"][h] is not None for e in subset) else None,
                "paired_excess_return": average(lambda e: e["outcomes"][h]["signed_return"] - e["baseline"][h]) if subset and all(e["baseline"][h] is not None for e in subset) else None,
                "excess_ci": interval(lambda e: e["outcomes"][h]["signed_return"] - e["baseline"][h]) if subset and all(e["baseline"][h] is not None for e in subset) else None})
    return summaries


def run(adapter: ReadOnlyExploratoryAdapter, partitions, config, provenance):
    if set(config) != {"strategy", "contract", "start", "end", "eligibility"}:
        raise ValueError("Only fixed strategy, contract, date and eligibility controls are supported")
    if config["strategy"] != SPEC["id"] or config["contract"] != adapter.manifest.contract or config["eligibility"] != "complete_observed":
        raise ValueError("Unknown strategy, contract or eligibility policy")
    ordered = [partitions[d] for d in sorted(partitions)]
    ranks = {"development": 0, "validation": 1, "final_holdout": 2}
    if any(x not in ranks for x in ordered) or [ranks[x] for x in ordered] != sorted(ranks[x] for x in ordered):
        raise ValueError("Partitions must be predeclared and chronological")
    groups, excluded = eligible_sessions(adapter, partitions, config["start"], config["end"])
    events, candles = [], []
    lookup = {}
    for day, bars in groups.items():
        values, detected = detect(bars)
        for i, b in enumerate(bars):
            minute = b.end.astimezone(NY).strftime("%H:%M")
            lookup[day, minute] = (bars, i)
            candles.append({"time": stamp(b.timestamp), "available_at": stamp(b.end),
                "contract": b.contract, "session": day, "open": b.open, "high": b.high,
                "low": b.low, "close": b.close, "volume": b.volume, "vwap": values[i]})
        for event in detected:
            event.update(session=day, partition=partitions[day], outcomes=label(bars, event["bar_index"], event["direction"]))
            events.append(event)
    for event in events:
        minute = parse(event["signal_at"]).astimezone(NY).strftime("%H:%M")
        controls = [label(*lookup[day, minute], event["direction"]) for day in groups
                    if day != event["session"] and partitions[day] == event["partition"] and (day, minute) in lookup]
        event["baseline"] = {h: mean(c[h]["signed_return"] for c in controls) if controls else None for h in map(str, (5, 10, 15))}
        event["baseline_sessions"] = len(controls)
    result = {"specification": SPEC, "configuration": config, "provenance": provenance,
        "code_sha256": code_version(), "dataset_sha256": adapter.manifest.dataset_sha256,
        "calendar_sha256": adapter.manifest.calendar_identity["calendar_sha256"],
        "contract": adapter.manifest.contract, "coverage": sorted(groups), "excluded_sessions": excluded,
        "partitions": {d: partitions[d] for d in groups}, "events": events, "candles": candles,
        "metrics": summarize(events), "event_count": len(events), "session_count": len(groups),
        "hypothetical_net_usd_per_event": mean(e["outcomes"]["cost_scenario"]["net_usd"] for e in events) if events else None,
        "strategy_metrics": {"sharpe": None, "profit_factor": None, "equity_curve": None,
            "reason": "Event prediction and independent cost scenarios only; no executable portfolio or accounting model implemented."},
        "uncertainty": "Session-block percentile bootstrap; 500 draws; seed 1701; familywise 95% Bonferroni over 18 intervals; unavailable below 5 event sessions. Descriptive, overlapping outcomes may remain dependent.",
        "validation": {"complete_sessions": True, "fixed_specification": True, "no_holdout": True,
                       "contract_alignment": True, "publication_at_or_before_close": True},
        "strict_eligible": False, "status": "completed"}
    result["experiment_id"] = digest(result)
    return result


def replay_view(result, as_of=None):
    """During replay send neither outcomes nor ANY full-sample derived statistics."""
    if as_of is None:
        return result
    at = parse(as_of)
    return {"experiment_id": result["experiment_id"], "contract": result["contract"], "replay_at": stamp(at),
        "candles": [b for b in result["candles"] if parse(b["available_at"]) <= at],
        "events": [{k: e[k] for k in ("bar_time", "signal_at", "contract", "direction", "classification", "vwap", "reference_close", "session")}
                   for e in result["events"] if parse(e["signal_at"]) <= at],
        "metrics_unavailable": "All outcomes, baselines, counts and aggregate statistics hidden during replay"}
