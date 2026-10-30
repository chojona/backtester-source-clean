"""Deterministic, synthetic-ready point-in-time feature measurements.

Bars are identified by their *open* time. An observation is usable only after
its close and recorded arrival. All windows are complete, ordered UTC grids.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math

from .feature_contracts import FEATURE_SCHEMA_VERSION, parse_utc, validate_feature_contract
from .volatility import log_return, realized_variance, segmented_bipower_variation

VERSION = "quant-feature-v1.0.0"
MINUTE = timedelta(minutes=1)


class FeatureError(ValueError):
    pass


def stamp(value):
    """Canonical UTC timestamp; reject offset representations without UTC."""
    if isinstance(value, str):
        value = parse_utc(value, "feature")
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise FeatureError("timestamp must be UTC")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Observation:
    instrument: str
    source_id: str
    session: str
    segment: str
    start: str
    end: str
    available_at: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    contract: str

    def __post_init__(self):
        if not self.instrument or not self.source_id or not self.session or not self.segment or not self.contract:
            raise FeatureError("observation identity and provenance are required")
        start, end, available = map(lambda x: parse_utc(x, "observation"),
                                    (self.start, self.end, self.available_at))
        if start >= end or end > available:
            raise FeatureError("observation cannot arrive before bar close")
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(math.isfinite(x) for x in values) or min(values[:4]) <= 0 or self.volume < 0:
            raise FeatureError("invalid OHLCV")
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close, self.high):
            raise FeatureError("invalid OHLC")


@dataclass(frozen=True)
class FeatureOutput:
    feature_id: str
    feature_version: str
    instrument: str
    source_id: str
    window_start: str
    window_end: str
    calculated_at: str
    source_publication_at: str | None
    available_at: str
    decision_at: str
    availability_phase: str
    missing_data_policy: str
    revision_policy: str
    dependency_hashes: tuple[str, ...]
    value: float
    units: str
    classification: str = "SYNTHETIC"

    def __post_init__(self):
        if not self.feature_id or not self.instrument or not self.source_id or not self.units:
            raise FeatureError("feature identity, provenance, and units are required")
        if self.feature_version != VERSION or self.classification != "SYNTHETIC":
            raise FeatureError("unsupported feature version or evidence class")
        if self.missing_data_policy != "fail_closed" or self.revision_policy != "reject_revisions":
            raise FeatureError("unsupported missing-data or revision policy")
        if self.availability_phase not in {"intrabar", "bar_close", "arrival_delay", "published"}:
            raise FeatureError("availability phase is required")
        times = [parse_utc(x, "feature") for x in (self.window_start, self.window_end,
                 self.calculated_at, self.available_at, self.decision_at)]
        if not times[0] < times[1] <= times[2] <= times[3] <= times[4]:
            raise FeatureError("feature depends on future or unavailable data")
        if self.source_publication_at is not None:
            publication = parse_utc(self.source_publication_at, "publication")
            if publication > times[3]:
                raise FeatureError("publication after availability")
        if not self.dependency_hashes or any(len(x) != 64 or any(c not in "0123456789abcdef" for c in x)
                                             for x in self.dependency_hashes):
            raise FeatureError("valid dependency hashes are required")
        if not math.isfinite(self.value):
            raise FeatureError("feature value must be finite")

    @property
    def content_sha256(self):
        return digest(asdict(self))

    def to_contract_v1(self):
        """Compatible Step 10 contract projection; output hash remains separate."""
        decision = parse_utc(self.decision_at, "decision")
        observed = parse_utc(self.window_end, "observation")
        seconds = max(1, math.ceil((decision - observed).total_seconds()))
        result = {"schema_version": FEATURE_SCHEMA_VERSION, "feature_id": self.feature_id,
            "observation_timestamp": self.window_end,
            "source_publication_timestamp": self.source_publication_at,
            "data_availability_timestamp": self.available_at,
            "decision_timestamp": self.decision_at,
            "lookback": {"bars": seconds, "bar_seconds": 1},
            "revision_policy": self.revision_policy, "adjustment_policy": "raw_unadjusted",
            "missing_data_policy": self.missing_data_policy,
            "required_evidence": ["source_publication"] if self.source_publication_at else [self.source_id],
            "revisions": []}
        return validate_feature_contract(result)


def _window(bars, decision_at, *, expected=None, same_session=True):
    bars = tuple(bars)
    decision = parse_utc(stamp(decision_at), "decision")
    if not bars or (expected is not None and len(bars) != expected):
        raise FeatureError("incomplete observation window")
    first = bars[0]
    previous = None
    for bar in bars:
        if (bar.instrument, bar.source_id, bar.contract) != (first.instrument, first.source_id, first.contract):
            raise FeatureError("mixed instrument or source")
        if same_session and bar.session != first.session:
            raise FeatureError("window crosses a session")
        if previous and parse_utc(bar.start, "start") != parse_utc(previous.end, "end"):
            raise FeatureError("missing or overlapping bar")
        if parse_utc(bar.available_at, "arrival") > decision:
            raise FeatureError("bar arrived after decision")
        previous = bar
    return bars


def _emit(feature_id, value, bars, decision_at, units, *, phase="bar_close", publication=None):
    bars = tuple(bars)
    available = max((bar.available_at for bar in bars), key=lambda x: parse_utc(x, "arrival"))
    if parse_utc(available, "arrival") > parse_utc(bars[-1].end, "bar close"):
        phase = "arrival_delay"
    return FeatureOutput(feature_id, VERSION, bars[0].instrument, bars[0].source_id,
        bars[0].start, bars[-1].end, bars[-1].end, publication,
        available,
        stamp(decision_at), phase, "fail_closed", "reject_revisions",
        tuple(digest(asdict(bar)) for bar in bars), value, units)


def price_volume(feature_id, bars, decision_at, *, window=None):
    """Completed-bar log return, typical-price VWAP, extrema, and volume statistics."""
    bars = _window(bars, decision_at, expected=window)
    if feature_id == "log_return":
        if len(bars) != 2:
            raise FeatureError("log return needs two closes")
        value, units = log_return(bars[0].close, bars[1].close), "log_return"
    elif feature_id == "vwap":
        from .features import VWAP
        vwap = VWAP("typical")
        for bar in bars:
            vwap.update(bar)
        if vwap.value is None:
            raise FeatureError("zero-volume VWAP")
        value, units = vwap.value, "price_points"
    elif feature_id in {"high", "low", "previous_session_high", "previous_session_low",
                        "overnight_high", "overnight_low", "opening_range_high", "opening_range_low"}:
        if feature_id.startswith("overnight") and any(b.segment != "OVERNIGHT" for b in bars):
            raise FeatureError("overnight window contains other segments")
        if feature_id.startswith("opening_range") and any(b.segment != "RTH" for b in bars):
            raise FeatureError("opening range contains other segments")
        value = max(b.high for b in bars) if feature_id.endswith("high") or feature_id == "high" else min(b.low for b in bars)
        units = "price_points"
    elif feature_id in {"volume_sum", "volume_mean"}:
        value = math.fsum(b.volume for b in bars)
        if feature_id == "volume_mean":
            value /= len(bars)
        units = "contracts" if feature_id == "volume_sum" else "contracts_per_bar"
    else:
        raise FeatureError("unknown price or volume feature")
    return _emit(feature_id, value, bars, decision_at, units)


def session_level(feature_id, bars, decision_at, *, expected_bars, current_session,
                  segment_open, previous_session=None):
    """Completed prior session, overnight, or opening range; never developing levels."""
    bars = _window(bars, decision_at, expected=expected_bars)
    if parse_utc(bars[0].start, "start") != parse_utc(stamp(segment_open), "segment open") or any(
        parse_utc(b.end, "end") - parse_utc(b.start, "start") != MINUTE for b in bars):
        raise FeatureError("session level requires complete one-minute segment prefix")
    if feature_id.startswith("previous_session"):
        if (previous_session is None or bars[0].session != previous_session or
                previous_session >= current_session or any(b.segment != "RTH" for b in bars)):
            raise FeatureError("prior completed RTH session required")
    elif feature_id.startswith("overnight"):
        if bars[0].session != current_session or any(b.segment != "OVERNIGHT" for b in bars):
            raise FeatureError("complete current overnight segment required")
    elif feature_id.startswith("opening_range"):
        if bars[0].session != current_session or any(b.segment != "RTH" for b in bars):
            raise FeatureError("complete current opening range required")
    else:
        raise FeatureError("unknown session level")
    return price_volume(feature_id, bars, decision_at, window=expected_bars)


def volatility(feature_id, bars, decision_at):
    """Nonoverlapping one-minute close returns, with fixed 5/15 minute blocks."""
    bars = _window(bars, decision_at)
    if any(parse_utc(b.end, "end") - parse_utc(b.start, "start") != MINUTE for b in bars):
        raise FeatureError("volatility requires one-minute bars")
    if len(bars) < 2:
        raise FeatureError("volatility needs two prices")
    returns = [log_return(a.close, b.close) for a, b in zip(bars, bars[1:])]
    if feature_id == "rv_1m":
        value = realized_variance(returns)
    elif feature_id in {"rv_5m", "rv_15m"}:
        size = 5 if feature_id == "rv_5m" else 15
        if len(returns) % size:
            raise FeatureError("incomplete coarse return block")
        coarse = [log_return(bars[i].close, bars[i + size].close)
                  for i in range(0, len(returns), size)]
        value = realized_variance(coarse)
    elif feature_id == "bpv":
        labels = [b.segment if a.segment == b.segment else f"boundary:{index}"
                  for index, (a, b) in enumerate(zip(bars, bars[1:]))]
        value = segmented_bipower_variation(returns, labels)
        if value is None:
            raise FeatureError("no within-segment return pair")
    else:
        raise FeatureError("unknown volatility feature")
    return _emit(feature_id, value, bars, decision_at, "log_return_squared")


@dataclass(frozen=True)
class CompletedSessionRV:
    session: str
    expected_bars: int
    observed_bars: int
    output: FeatureOutput

    def __post_init__(self):
        if (self.expected_bars < 2 or self.observed_bars != self.expected_bars or
                len(self.output.dependency_hashes) != self.expected_bars or
                parse_utc(self.output.window_end, "end") - parse_utc(self.output.window_start, "start")
                != self.expected_bars * MINUTE):
            raise FeatureError("daily RV session is incomplete")
        if self.output.feature_id != "rv_1m":
            raise FeatureError("daily RV must use one-minute variance")


def completed_session_rv(bars, decision_at, *, expected_bars):
    rows = _window(bars, decision_at, expected=expected_bars)
    return CompletedSessionRV(rows[0].session, expected_bars, len(rows),
                              volatility("rv_1m", rows, decision_at))


def har_lags(completed_sessions, decision_at, *, expected_sessions):
    """Ordered prior complete daily RVs on an externally certified session roster."""
    rows = tuple(completed_sessions)
    expected = tuple(expected_sessions)
    if len(rows) < 22 or len(expected) != 22 or tuple(r.session for r in rows[-22:]) != expected:
        raise FeatureError("HAR requires 22 distinct completed sessions")
    if len(set(expected)) != 22 or list(expected) != sorted(expected):
        raise FeatureError("HAR session roster is not ordered")
    if any(not isinstance(r, CompletedSessionRV) or r.output.feature_version != VERSION for r in rows):
        raise FeatureError("HAR requires compatible daily RV")
    outputs = tuple(r.output for r in rows)
    if any(parse_utc(a.window_end, "end") >= parse_utc(b.window_start, "start")
           for a, b in zip(outputs, outputs[1:])):
        raise FeatureError("HAR sessions must be strictly ordered")
    if any(parse_utc(r.available_at, "arrival") > parse_utc(stamp(decision_at), "decision") for r in outputs):
        raise FeatureError("HAR target leakage")
    tail = outputs[-22:]
    result = []
    for name, group in (("har_rv_d", tail[-1:]), ("har_rv_w", tail[-5:]), ("har_rv_m", tail)):
        result.append(FeatureOutput(name, VERSION, group[0].instrument, group[0].source_id,
            group[0].window_start, group[-1].window_end, group[-1].calculated_at, None,
            max((r.available_at for r in group), key=lambda x: parse_utc(x, "arrival")),
            stamp(decision_at), "bar_close", "fail_closed", "reject_revisions",
            tuple(r.content_sha256 for r in group), math.fsum(r.value for r in group) / len(group),
            "log_return_squared"))
    return tuple(result)


def align_last_known(observations, instruments, decision_at, max_staleness, *, session=None):
    """Pick latest arrived completed observation per instrument, or explicit None."""
    decision = parse_utc(stamp(decision_at), "decision")
    if max_staleness < timedelta(0):
        raise FeatureError("negative staleness")
    selected = {}
    for instrument in instruments:
        candidates = [b for b in observations if b.instrument == instrument
                      and (session is None or b.session == session)
                      and parse_utc(b.end, "end") <= decision
                      and parse_utc(b.available_at, "arrival") <= decision
                      and decision - parse_utc(b.end, "end") <= max_staleness]
        selected[instrument] = max(candidates, key=lambda b: parse_utc(b.end, "end")) if candidates else None
    return selected


def cross_asset_return(observations, instrument, decision_at, max_staleness):
    """Two last known consecutive observations from one session and source."""
    latest = align_last_known(observations, (instrument,), decision_at, max_staleness)[instrument]
    if latest is None:
        return None
    prior = [b for b in observations if b.instrument == instrument
             and parse_utc(b.end, "end") == parse_utc(latest.start, "start")
             and b.session == latest.session and b.source_id == latest.source_id]
    if not prior:
        return None
    return price_volume("log_return", (prior[0], latest), decision_at)


@dataclass(frozen=True)
class MacroRelease:
    event_id: str
    source_id: str
    scheduled_at: str
    published_at: str
    available_at: str
    embargo_until: str
    value: float
    revision: int = 0

    def __post_init__(self):
        times = [parse_utc(x, "macro") for x in (self.scheduled_at, self.published_at,
                                                  self.available_at, self.embargo_until)]
        if times[1] > times[2] or self.revision < 0 or not self.event_id or not self.source_id:
            raise FeatureError("invalid macro release provenance")
        if not math.isfinite(self.value):
            raise FeatureError("invalid macro value")


def macro_feature(releases, event_id, decision_at):
    decision = parse_utc(stamp(decision_at), "decision")
    candidates = [r for r in releases if r.event_id == event_id
                  and max(parse_utc(r.available_at, "availability"),
                          parse_utc(r.embargo_until, "embargo")) <= decision]
    if not candidates:
        return None
    latest = max(candidates, key=lambda r: (r.revision, parse_utc(r.available_at, "availability")))
    if latest.revision:
        raise FeatureError("revision rejected by feature policy")
    published = parse_utc(latest.published_at, "publication")
    scheduled = parse_utc(latest.scheduled_at, "schedule")
    window_start = min(scheduled, published - timedelta(microseconds=1))
    return FeatureOutput("macro_" + event_id.lower(), VERSION, event_id, latest.source_id,
        stamp(window_start), latest.published_at, latest.published_at, latest.published_at,
        max(latest.available_at, latest.embargo_until), stamp(decision_at), "published",
        "fail_closed", "reject_revisions", (digest(asdict(latest)),), latest.value, "release_units")
