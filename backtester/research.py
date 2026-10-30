"""Event discovery is causal; forward labeling runs offline after discovery."""
from dataclasses import dataclass, asdict
from datetime import timedelta
from statistics import mean, median
from .sessions import NY
from .strategy import Strategy
from .execution import Ambiguity


@dataclass(frozen=True)
class ReactionConfig:
    horizons_minutes: tuple = (5, 15, 30, 60)
    thresholds_points: tuple = (5, 10, 20, 30)
    through_points: float = 5.0
    approach_min_points: float = 1.0
    require_complete_week: bool = True
    level: str = "weekly_vwap"  # session_vwap enables the next experiment without another indicator stack

    def __post_init__(self):
        from math import isfinite
        if self.level not in ("weekly_vwap", "session_vwap"):
            raise ValueError("Research level must be weekly_vwap or session_vwap")
        if not self.horizons_minutes or any(not isinstance(h, int) or h <= 0 for h in self.horizons_minutes):
            raise ValueError("Research horizons must be positive integer minutes")
        if not self.thresholds_points or any(not isfinite(p) or p <= 0 for p in self.thresholds_points):
            raise ValueError("Reaction thresholds must be finite and positive")
        if not isfinite(self.through_points) or self.through_points <= 0 or not isfinite(self.approach_min_points) or self.approach_min_points <= 0:
            raise ValueError("Approach and through distances must be finite and positive")


class WeeklyVWAPReaction(Strategy):
    name = "weekly-vwap-reaction-v1"
    version = "1.0.0"

    def __init__(self, config=None):
        self.config = config or ReactionConfig()
        self.parameters = asdict(self.config)
        self.events = []
        self.previous = None
        self.seen = set()
        self.approach_day = None
        self.approach_distance = 0.0
        self.approach_side = None
        self.approach_path = 0.0
        self.approach_last_close = None

    def on_bar(self, context):
        current = context.features
        previous = self.previous
        self.previous = (context.bar, dict(current), dict(context.account))
        if context.bar.bar_state != "TRADED" or context.bar.coverage_state == "UNKNOWN":
            return ()
        if previous is None:
            return ()
        prior_bar, prior_features, prior_account = previous
        level = prior_features[self.config.level]
        day = current["trading_date"]
        week_changed = day - timedelta(days=day.weekday()) != prior_features["trading_date"] - timedelta(days=prior_features["trading_date"].weekday())
        if level is None or week_changed or prior_bar.contract != context.bar.contract:
            return ()
        if self.config.require_complete_week:
            flag = "weekly_vwap_complete" if self.config.level == "weekly_vwap" else "session_vwap_complete"
            if not prior_features[flag] or not current[flag]:
                return ()
        if self.config.level == "session_vwap" and day != prior_features["trading_date"]:
            return ()
        if day != self.approach_day:
            self.approach_day, self.approach_distance, self.approach_side = day, 0.0, None
            self.approach_path, self.approach_last_close = 0.0, None
        scale = context.account["research_scale"]
        distance = (prior_bar.close - level) / scale
        side = 1 if distance > 0 else -1 if distance < 0 else 0
        if abs(distance) >= self.config.approach_min_points:
            if side != self.approach_side:
                self.approach_distance = 0.0
                self.approach_path, self.approach_last_close = 0.0, None
            self.approach_side = side
            self.approach_distance = max(self.approach_distance, abs(distance))
        if self.approach_last_close is not None:
            self.approach_path += abs(prior_bar.close - self.approach_last_close) / scale
        self.approach_last_close = prior_bar.close
        touched = context.bar.low <= level <= context.bar.high
        if day in self.seen or not touched or side == 0 or side != self.approach_side:
            return ()
        self.seen.add(day)
        local = context.timestamp.astimezone(NY)
        event = dict(timestamp=context.timestamp, bar_open=context.bar.timestamp,
                     instrument=context.bar.symbol, contract=context.bar.contract,
                     trading_date=day, session=current["session"],
                     level=self.config.level, reference_level=level, raw_reference_level=(level - context.account["research_offset"]) / scale,
                     research_scale=scale, direction_of_approach="from_above" if side == 1 else "from_below",
                     away_direction=side, distance_from_vwap_points=(context.bar.close - level) / scale,
                     price_relative_to_session_vwap=(context.bar.close - current["session_vwap"]) / scale if current["session_vwap"] is not None else None,
                     PDH=current.get("PDH"), PDL=current.get("PDL"), ONH=current.get("ONH"), ONL=current.get("ONL"),
                     ATR_points=current["ATR"] / scale if current["ATR"] is not None else None,
                     time_of_day=local.strftime("%H:%M:%S"), weekday=local.strftime("%A"),
                     distance_traveled_before_touch_points=self.approach_path + abs(distance),
                     maximum_pre_touch_departure_points=self.approach_distance,
                     approach_path_basis="completed close-to-close path plus final distance to lagged VWAP; intrabar path unknown",
                     weekly_vwap_complete=current["weekly_vwap_complete"],
                     session_vwap_complete=current["session_vwap_complete"],
                     touch_definition="bar range spans PREVIOUS completed-bar VWAP; detected at close",
                     event_granularity_seconds=context.bar.duration.total_seconds())
        self.events.append(event)
        return ()


def label_events(events, selected, calendar, config, ambiguity=Ambiguity.CONSERVATIVE):
    """Future information is used ONLY here. It is never handed back to strategies."""
    from bisect import bisect_left
    timestamps = [item.raw.timestamp for item in selected]
    results = []
    ambiguity = Ambiguity(ambiguity)
    for event in events:
        start = event["timestamp"]
        index = bisect_left(timestamps, start)
        level, scale, direction = event["reference_level"], event["research_scale"], event["away_direction"]
        row = dict(event)
        horizons = {}
        for minutes in config.horizons_minutes:
            deadline = start + timedelta(minutes=minutes)
            expected = start
            favorable = adverse = 0.0
            future = []
            reason = None
            for item in selected[index:]:
                if item.raw.timestamp >= deadline:
                    break
                if item.raw.contract != event["contract"] or item.roll:
                    reason = "contract_roll"
                    break
                if item.raw.timestamp != expected:
                    reason = "missing_interval_or_market_closure"
                    break
                if item.raw.end > deadline:
                    reason = "horizon_not_aligned_to_interval"
                    break
                if calendar.classify(item.raw.timestamp).trading_date != event["trading_date"]:
                    reason = "trading_date_boundary"
                    break
                if item.raw.coverage_state == "UNKNOWN":
                    reason = "unknown_provider_coverage"
                    break
                if item.raw.bar_state == "NO_TRADE":
                    expected = item.raw.end
                    continue
                bar = item.research
                best = ((bar.high if direction == 1 else bar.low) - level) * direction / scale
                worst = ((bar.low if direction == 1 else bar.high) - level) * direction / scale
                favorable, adverse = max(favorable, best), max(adverse, -worst)
                future.append(item)
                expected = item.raw.end
            complete = reason is None and expected == deadline
            if not complete and reason is None:
                reason = "dataset_end_or_market_closure"
            horizons[str(minutes)] = dict(complete=complete, censored_reason=reason,
                                         mfe_points=favorable if complete else None,
                                         mae_points=adverse if complete else None,
                                         observed_bars=len(future))
        max_minutes = max(config.horizons_minutes)
        outcomes = {}
        for threshold in config.thresholds_points:
            outcome, ambiguous_count, observed_to = None, 0, start
            for item in selected[index:]:
                if item.raw.timestamp >= start + timedelta(minutes=max_minutes):
                    break
                if item.raw.contract != event["contract"] or item.raw.timestamp != observed_to or item.roll:
                    break
                if item.raw.end > start + timedelta(minutes=max_minutes):
                    break
                if calendar.classify(item.raw.timestamp).trading_date != event["trading_date"]:
                    break
                if item.raw.coverage_state == "UNKNOWN":
                    break
                if item.raw.bar_state == "NO_TRADE":
                    observed_to = item.raw.end
                    continue
                bar = item.research
                favorable = direction * ((bar.high if direction == 1 else bar.low) - level) / scale
                adverse = -direction * ((bar.low if direction == 1 else bar.high) - level) / scale
                opened = direction * (bar.open - level) / scale
                hit, crossed = favorable >= threshold, adverse >= config.through_points
                if hit and crossed:
                    if opened >= threshold:
                        outcome = True
                    elif opened <= -config.through_points:
                        outcome = False
                    else:
                        ambiguous_count += 1
                        outcome = ambiguity in (Ambiguity.OPTIMISTIC, Ambiguity.TARGET_FIRST)
                    break
                if hit or crossed:
                    outcome = hit
                    break
                observed_to = item.raw.end
            # None distinguishes no passage within horizon from truncated observations.
            complete = horizons[str(max_minutes)]["complete"]
            outcomes[str(threshold)] = dict(away_before_through=outcome,
                ambiguous_bars=ambiguous_count, policy=ambiguity.value,
                resolved=outcome is not None,
                censored=outcome is None and not complete,
                no_passage_within_horizon=outcome is None and complete)
        row["forward"], row["threshold_outcomes"] = horizons, outcomes
        results.append(row)
    return results


def quantiles(values):
    if not values:
        return dict(count=0, mean=None, median=None, p10=None, p90=None)
    ordered = sorted(values)
    def quantile(fraction):
        index = (len(ordered) - 1) * fraction
        low = int(index)
        return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (index - low)
    return dict(count=len(values), mean=mean(values), median=median(values), p10=quantile(.1), p90=quantile(.9))


def research_statistics(events, config):
    statistics = dict(events=len(events), horizon_distributions={}, threshold_results={})
    for minutes in config.horizons_minutes:
        complete = [e["forward"][str(minutes)] for e in events if e["forward"][str(minutes)]["complete"]]
        statistics["horizon_distributions"][str(minutes)] = dict(
            complete=len(complete), censored=len(events) - len(complete),
            MFE=quantiles([e["mfe_points"] for e in complete]),
            MAE=quantiles([e["mae_points"] for e in complete]))
    for threshold in config.thresholds_points:
        rows = [e["threshold_outcomes"][str(threshold)] for e in events]
        successes = sum(r["away_before_through"] is True for r in rows)
        failures = sum(r["away_before_through"] is False for r in rows)
        statistics["threshold_results"][str(threshold)] = dict(successes=successes, failures=failures,
            censored=sum(r["censored"] for r in rows), unresolved=sum(not r["resolved"] for r in rows),
            no_passage=sum(r["no_passage_within_horizon"] for r in rows),
            ambiguous_bars=sum(r["ambiguous_bars"] for r in rows),
            success_rate_resolved=successes / (successes + failures) if successes + failures else None)
    return statistics
