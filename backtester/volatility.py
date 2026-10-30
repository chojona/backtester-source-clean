"""Causal raw-contract realized measurements. Definitions: docs/VOLATILITY.md.

Scalar functions require finite, regularly sampled log returns with no gaps.
The streaming layer enforces time/session/contract boundaries and reports coverage.
All units are unannualized log-return powers, never price points or ATR.
"""
from dataclasses import dataclass
from datetime import timedelta
import math

from .data import Bar

MINUTE = timedelta(minutes=1)
BPV_ESTIMATOR_VERSION = "bpv-segment-v1.0.0"
LEGACY_HISTORICAL_BPV_VERSION = "bpv-all-adjacent-v0.0.0"


def log_return(previous, current):
    """log(current/previous); positive finite prices only. Stable near equality."""
    if not all(math.isfinite(p) and p > 0 for p in (previous, current)):
        raise ValueError("Log returns require positive finite prices")
    difference = current - previous
    if abs(difference) <= previous / 2:
        return math.log1p(difference / previous)
    return math.log(current) - math.log(previous)


def _returns(values):
    result = tuple(values)
    if not all(math.isfinite(r) for r in result):
        raise ValueError("Returns must be finite; split missing intervals explicitly")
    return result


def realized_variance(returns):
    """Total quadratic variation proxy: sum(r_i**2), empty input -> None."""
    r = _returns(returns)
    return math.fsum(x * x for x in r) if r else None


def semivariances(returns):
    """(RS+, RS-) = sums of r² for strictly positive / negative returns."""
    r = _returns(returns)
    if not r:
        return None, None
    return (math.fsum(x*x for x in r if x > 0),
            math.fsum(x*x for x in r if x < 0))


def bipower_variation(returns):
    """Continuous-variation proxy (pi/2)*sum |r_i r_(i-1)|.

    No n/(n-1) correction; fewer than two returns -> None. No pairing across gaps.
    """
    r = _returns(returns)
    return math.pi / 2 * math.fsum(abs(a*b) for a, b in zip(r, r[1:])) if len(r) >= 2 else None


def segmented_bipower_variation(returns, segments):
    """Version 1 BPV: pair consecutive returns only within one calendar segment.

    The caller must supply one segment label per regularly sampled return and
    split any time gap or contract change before calling this scalar function.
    """
    r, labels = _returns(returns), tuple(segments)
    if len(r) != len(labels):
        raise ValueError("One calendar segment label per return required")
    products = [abs(r[i - 1] * r[i]) for i in range(1, len(r))
                if labels[i - 1] == labels[i]]
    return math.pi / 2 * math.fsum(products) if products else None


def threshold_bipower_variation(returns, squared_thresholds):
    """Normalized TMPV[1,1], Corsi/Pirino/Reno (2010), Definition 2.2.

    (pi/2) sum |r_i r_(i-1)| 1[r_i²<=theta_i] 1[r_(i-1)²<=theta_(i-1)].
    Thresholds must be positive finite and supplied ex ante for causal use.
    This is uncorrected TBPV, not the paper's corrected C-TBPV implementation.
    """
    r, theta = _returns(returns), tuple(squared_thresholds)
    if len(r) != len(theta) or not all(math.isfinite(t) and t > 0 for t in theta):
        raise ValueError("One positive finite squared threshold per return required")
    return bipower_variation(x if x*x <= t else 0.0 for x, t in zip(r, theta))


def jump_variation(rv, bpv):
    """Nonnegative proxy max(RV-BPV,0), not a jump significance test.

    Finite-sample bias (QUA-40/L2): BPV pairs only adjacent returns, so
    boundary/gap pairs are dropped asymmetrically while RV keeps every
    squared return; with few returns this biases the proxy positive even
    under a continuous path. Never present it as a formal jump test.
    """
    if rv is None or bpv is None:
        return None
    if not all(math.isfinite(x) and x >= 0 for x in (rv, bpv)):
        raise ValueError("Variation must be finite and nonnegative")
    return max(rv - bpv, 0.0)


def realized_quarticity(returns):
    """RQ=(n/3) sum r_i**4 on an equal grid over a unit-normalized window.

    Estimates integrated sigma**4 under continuous/noiseless asymptotics.
    Jumps contaminate RQ; it is not a jump-robust standard error.
    """
    r = _returns(returns)
    return len(r) / 3 * math.fsum((x*x)**2 for x in r) if r else None


def realized_range(bars):
    """OHLC Parkinson sum: sum(log(H/L)**2)/(4 log(2)).

    Assumes positive finite highs/lows, continuous diffusion and negligible drift
    and noise. This uses continuous-path normalization, no tick-count correction.
    """
    values = [log_return(b.low, b.high)**2 for b in bars]
    return math.fsum(values) / (4 * math.log(2)) if values else None


@dataclass(frozen=True)
class VolatilityRecord:
    timestamp: object                  # availability time = last bar end, UTC
    instrument: str
    contract: str
    trading_date: object
    segment: str
    rv_1m: object
    rv_5m: object
    rv_15m: object
    bpv: object
    tbpv: object
    jump: object
    rs_positive: object
    rs_negative: object
    quarticity: object
    realized_range: object
    rv_rth: object
    rv_overnight: object
    rv_post_rth: object
    rv_intraday_to_now: object
    observed_rv: float
    observed_bars: int
    expected_bars_to_now: int
    missing_bars_to_now: int
    unknown_bars: int
    no_trade_bars: int
    prefix_complete: bool
    session_complete: bool
    segment_prefix_complete: bool
    samples_5m: int
    samples_15m: int
    covered_minutes_5m: int
    covered_minutes_15m: int
    tbpv_squared_threshold: object
    calendar_source: str
    profile_variance_share: object
    profile_volatility_share: object
    profile_reference_sessions: int
    profile_reference_through: object
    # Explicit complete-session RV (QUA-27/M1): rv_1m above is a
    # prefix-to-now measure whenever the prefix is complete; this field is
    # that same value ONLY when session_complete, otherwise None.
    rv_session: object = None


class _Accumulator:
    def __init__(self):
        self.returns = []
        self.products = []
        self.threshold_products = []
        self.ranges = []
        self.coarse = {5: [], 15: []}
        self.blocks = {5: [], 15: []}
        self.expected = self.observed = self.unknown = self.no_trade = 0
        self.previous_return = None

    @property
    def complete(self):
        return self.expected == self.observed and self.unknown == 0

    def add(self, bar, r, adjacent, offset, threshold):
        self.observed += 1
        self.no_trade += bar.bar_state == "NO_TRADE"
        if r is None:
            self.unknown += 1
        else:
            self.returns.append(r)
            self.ranges.append(realized_range([bar]))
            if adjacent and self.previous_return is not None:
                product = abs(r * self.previous_return)
                self.products.append(product)
                if threshold is not None:
                    self.threshold_products.append(product if max(r*r, self.previous_return**2) <= threshold else 0.0)
        self.previous_return = r
        for k in (5, 15):
            block = self.blocks[k]
            if offset % k == 0 or not adjacent or r is None:
                block.clear()
            if r is not None and (block or offset % k == 0):
                block.append(r)
            if offset % k == k - 1:
                if len(block) == k:
                    self.coarse[k].append(math.fsum(block))
                block.clear()

    def metrics(self, threshold):
        if not self.complete:
            return (None,) * 9
        rv = realized_variance(self.returns)
        bpv = math.pi / 2 * math.fsum(self.products) if self.products else None
        tbpv = math.pi / 2 * math.fsum(self.threshold_products) if self.threshold_products and threshold is not None else None
        positive, negative = semivariances(self.returns)
        return (rv, realized_variance(self.coarse[5]), realized_variance(self.coarse[15]),
                bpv, tbpv, positive, negative, realized_quarticity(self.returns),
                math.fsum(self.ranges) if self.ranges else None)


class RealizedVolatility:
    """Stream completed raw 1m bars, one instrument/contract stream per instance.

    update(bar, as_of=...) rejects unclosed, overlapping, off-grid and wrong-calendar
    bars before mutation. Contract changes reset the session measurement; never
    pass SelectedBar.research. Raw provenance cannot be inferred from price values.
    Calendar and threshold are configuration: do not mutate them during a run.

    Profiles use only prior fully covered, single-contract sessions with the same
    calendar grid. No current-session final RV is used as a live denominator.
    """
    def __init__(self, calendar, *, tbpv_squared_threshold=None):
        if tbpv_squared_threshold is not None and not (math.isfinite(tbpv_squared_threshold) and tbpv_squared_threshold > 0):
            raise ValueError("TBPV squared threshold must be positive finite")
        self.calendar = calendar
        self.threshold = tbpv_squared_threshold
        self.previous = None
        self.key = None
        self.total = None
        self.segments = None
        self._schedule = None
        self._profile = []
        self._history = []
        self._rolled_day = False
        self._last_record = None
        self._matching = []
        self._profile_denominator = 0.0

    def _grid(self, day):
        opened, closed, _, _ = self.calendar.bounds(day)
        result = []
        stamp = opened
        while stamp < closed:
            if self.calendar.valid_bar(stamp, MINUTE):
                result.append((stamp, self.calendar.classify(stamp)))
            stamp += MINUTE
        return result

    def update(self, bar, *, as_of):
        """Return immutable prefix measurements available at as_of (aware time)."""
        if not isinstance(bar, Bar):
            raise ValueError("Pass a raw Bar, or SelectedBar.raw explicitly")
        if as_of.tzinfo is None or bar.end > as_of:
            raise ValueError("Bar is not yet complete at as_of")
        if bar.duration != MINUTE or bar.timestamp.second or bar.timestamp.microsecond:
            raise ValueError("Require aligned one-minute bars")
        if self.previous and (bar.timestamp < self.previous.end or bar.symbol != self.previous.symbol):
            raise ValueError("Require chronological nonoverlapping bars for one instrument")
        info = self.calendar.classify(bar.timestamp)
        if info is None or not self.calendar.valid_bar(bar.timestamp, MINUTE):
            raise ValueError("Bar is outside the calendar")
        # Reject negative/zero prices, which Bar itself permits, before changing state.
        for value in (bar.open, bar.high, bar.low, bar.close):
            log_return(value, value)
        key = (bar.symbol, bar.contract, info.trading_date)
        changed = key != self.key
        if changed:
            same_day = self.key is not None and self.key[2] == info.trading_date
            if self._last_record and self._last_record.session_complete and not self._rolled_day and not same_day:
                self._history.append((self._last_record.timestamp, tuple(self._profile),
                                      self._shape))
            self._rolled_day = same_day
            self.key = key
            self.total = _Accumulator()
            self.segments = {name: _Accumulator() for name in ("OVERNIGHT", "RTH", "POST_RTH")}
            self._schedule = self._grid(info.trading_date)
            self._indices = {stamp: i for i, (stamp, _) in enumerate(self._schedule)}
            self._profile = []
            self._cursor = 0
            self._shape = tuple((stamp - info.open, item.session) for stamp, item in self._schedule)
            self._matching = [(available, values) for available, values, shape in self._history
                              if available <= bar.timestamp and shape == self._shape]
            self._profile_denominator = math.fsum(math.fsum(values) for _, values in self._matching)
        index = self._indices[bar.timestamp]
        for _, expected_info in self._schedule[self._cursor:index + 1]:
            self.total.expected += 1
            self.segments[expected_info.session].expected += 1
        self._cursor = index + 1
        previous_info = self.calendar.classify(self.previous.timestamp) if self.previous else None
        adjacent = (not changed and self.previous.end == bar.timestamp and
                    self.previous.coverage_state != "UNKNOWN")
        # Start/restart from the observed open. No close-to-close return across a gap.
        reference = self.previous.close if adjacent else bar.open
        r = None if bar.coverage_state == "UNKNOWN" else log_return(reference, bar.close)
        segment_adjacent = adjacent and previous_info.session == info.session
        offset = int((bar.timestamp - info.segment_open) / MINUTE)
        self.total.add(bar, r, segment_adjacent, offset, self.threshold)
        segment = self.segments[info.session]
        segment.add(bar, r, segment_adjacent, offset, self.threshold)
        self._profile.append(r*r if r is not None else None)
        rv, rv5, rv15, bpv, tbpv, pos, neg, rq, rr = self.total.metrics(self.threshold)
        def segment_rv(name):
            acc = self.segments[name]
            return realized_variance(acc.returns) if acc.complete else None
        # Normalize the past average slot variation by the past average daily RV.
        matching = self._matching
        share = (math.fsum(values[index] for _, values in matching) / self._profile_denominator
                 if self._profile_denominator > 0 else None)
        record = VolatilityRecord(
            bar.end, bar.symbol, bar.contract, info.trading_date, info.session,
            rv, rv5, rv15, bpv, tbpv, jump_variation(rv, bpv), pos, neg, rq, rr,
            segment_rv("RTH"), segment_rv("OVERNIGHT"), segment_rv("POST_RTH"), rv,
            math.fsum(x*x for x in self.total.returns), self.total.observed,
            self.total.expected, self.total.expected - self.total.observed,
            self.total.unknown, self.total.no_trade, self.total.complete,
            self.total.complete and bar.end == info.close, segment.complete,
            len(self.total.coarse[5]), len(self.total.coarse[15]),
            5 * len(self.total.coarse[5]), 15 * len(self.total.coarse[15]),
            self.threshold, self.calendar.source, share,
            math.sqrt(share) if share is not None else None, len(matching),
            max((available for available, _ in matching), default=None),
            rv if (self.total.complete and bar.end == info.close) else None)
        self.previous, self._last_record = bar, record
        return record
