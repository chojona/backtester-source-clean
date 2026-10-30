"""Causal contract selection. Liquidity decisions use completed sessions only."""
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from itertools import groupby
from .instruments import contract_root

CAUSAL_OI_STATE = "CAUSAL_CAPTURE_BOUND"  # declared label only; never proof


def causal_open_interest(bar, decision_stamp, *, _test_registry=None):
    """OI usable at ``decision_stamp``, or None for every provider alike (QUA-24).

    A caller-written ``CAUSAL_CAPTURE_BOUND`` string plus a caller-written
    timestamp -- exactly what an ordinary forged CSV or custom provider
    supplies -- is a *declaration*, not provenance, and is never accepted.
    A caller-supplied receipt object is likewise never accepted. OI is
    usable only when ``bar.open_interest_verification`` carries a
    ``VerifiedOpenInterest`` re-derived from hash-checked raw capture
    artifacts and a request manifest, bound to provider/dataset/request/
    instrument/contract, the exact bar timestamp and bar event timestamp,
    quantity and capture time, that verified availability is at or
    before the decision stamp, AND the capture manifest hash is still
    present in the approved evidence registry (production registry by
    default; ``_test_registry`` is synthetic plumbing only). This
    downstream recheck means a test-minted or formerly approved bar is
    refused once approval is absent/revoked. Missing, naive,
    invalid-timezone, retrospective or future-dated evidence is treated
    as absent: the decision stays unresolved, no roll is booked. Invalid
    timezone objects return None here instead of raising.
    """
    try:
        if bar.open_interest is None:
            return None
        from .data import VerifiedOpenInterest, _aware, _verified_digest
        from .evidence_registry import resolve_registry
        verified = getattr(bar, "open_interest_verification", None)
        if not isinstance(verified, VerifiedOpenInterest):
            return None
        if not resolve_registry(_test_registry).capture_approved(
                verified.capture_manifest_sha256, provider=bar.provider, dataset=bar.dataset):
            return None
        if verified.quantity != bar.open_interest or verified.provider != bar.provider \
                or verified.dataset != bar.dataset or verified.request_id != bar.request_id \
                or verified.instrument_id != bar.instrument_id \
                or verified.contract != bar.contract \
                or _aware(verified.bar_timestamp) != _aware(bar.timestamp) \
                or verified.bar_source_ts_event_ns != bar.source_ts_event_ns \
                or verified.binding_sha256 != _verified_digest(verified):
            return None
        available = _aware(verified.available_at)
        decision = _aware(decision_stamp)
        if available is None or decision is None or available > decision:
            return None
        return bar.open_interest
    except Exception:
        return None


@dataclass(frozen=True)
class RollConfig:
    policy: str = "fixed"
    days_before_expiration: int = 5
    expirations: object = None
    initial_contract: object = None
    adjustment: str = "forward_additive"
    position_policy: str = "flatten"
    defer_until_traded_pair: bool = False

    def __post_init__(self):
        if self.policy not in ("fixed", "volume", "open_interest"):
            raise ValueError("Unknown roll policy")
        if self.adjustment not in ("forward_additive", "forward_ratio", "unadjusted_reset"):
            raise ValueError("Online research accepts only causal adjustments; final back-adjusted history is not causal")
        if self.position_policy not in ("flatten", "reopen"):
            raise ValueError("Roll position policy must be flatten or reopen")
        if self.days_before_expiration < 0:
            raise ValueError("Roll days cannot be negative")
        for contract, expiration in (self.expirations or {}).items():
            contract_root(contract)
            date.fromisoformat(expiration)


@dataclass(frozen=True)
class RollRecord:
    timestamp: object
    old_contract: str
    new_contract: str
    old_open: float
    new_open: float
    price_difference: float
    policy: str
    adjustment: str


@dataclass(frozen=True)
class SelectedBar:
    raw: object
    research: object
    roll: object = None
    scale: float = 1.0
    offset: float = 0.0


class ContinuousSeries:
    def __init__(self, calendar, config, *, _test_registry=None):
        # _test_registry: synthetic plumbing only. Production (default)
        # rechecks every verified OI manifest against the approved
        # evidence registry in config/approved_evidence.json.
        self.calendar, self.config = calendar, config
        self._test_registry = _test_registry
        self.records = []
        self.warnings = []

    def select(self, bars):
        self.records = []
        contracts = sorted({b.contract for b in bars})
        if len(contracts) > 1:
            if not self.config.expirations or set(contracts) - set(self.config.expirations):
                raise ValueError("Every constituent contract requires an explicit expiration date")
            contracts.sort(key=lambda c: self.config.expirations[c])
            if len(set(self.config.expirations[c] for c in contracts)) != len(contracts):
                raise ValueError("Contract expiration dates must be distinct")
        active = self.config.initial_contract or contracts[0]
        if active not in contracts:
            raise ValueError("Initial contract not in data")
        totals, oi, coverage = {}, {}, {}
        last_day, previous_totals, previous_oi = None, {}, {}
        previous_stamp = None
        duration = bars[0].duration
        scale, offset = 1.0, 0.0
        pending_candidate = None
        for stamp, group in groupby(bars, key=lambda b: b.timestamp):
            grouped = tuple(group)
            snapshot = {b.contract: b for b in grouped}
            if len(snapshot) != len(grouped):
                raise ValueError("Duplicate contract timestamp in roll panel")
            if previous_stamp is not None and stamp <= previous_stamp:
                raise ValueError("Roll panel must be strictly chronological across snapshots")
            previous_stamp = stamp
            info = self.calendar.classify(stamp)
            day = info.trading_date
            rollover = None
            if last_day is not None and day != last_day:
                previous_totals, previous_oi = totals, oi
                # Comparing incomplete or unequal contract coverage can bias liquidity selection.
                needed = contracts[contracts.index(active):contracts.index(active) + 2]
                if self.config.policy in ("volume", "open_interest") and len(needed) > 1:
                    if len({tuple(sorted(coverage.get(c, set()))) for c in needed}) > 1:
                        raise ValueError("Liquidity roll requires matched prior-session contract coverage")
                if self.config.policy in ("volume", "open_interest") and len(contracts) > 1:
                    opened, closed, _, _ = self.calendar.bounds(last_day)
                    expected = set()
                    probe = opened
                    while probe < closed:
                        if self.calendar.valid_bar(probe, duration):
                            expected.add(probe)
                        probe += duration
                    needed = contracts[contracts.index(active):contracts.index(active) + 2]
                    if any(coverage.get(contract, set()) != expected for contract in needed):
                        raise ValueError("Liquidity roll requires complete prior-session coverage for active and next contract")
                totals, oi, coverage = {}, {}, {}
            if day != last_day and len(contracts) > 1:
                index = contracts.index(active)
                if index < len(contracts) - 1:
                    candidate = contracts[index + 1]
                    if self.config.policy == "fixed":
                        roll_day = date.fromisoformat(self.config.expirations[active]) - timedelta(days=self.config.days_before_expiration)
                        switch = day >= roll_day
                    elif self.config.policy == "volume":
                        switch = previous_totals.get(candidate, 0) > previous_totals.get(active, float("inf"))
                    else:
                        if last_day is not None and (active not in previous_oi or candidate not in previous_oi):
                            raise ValueError("Open-interest roll requires point-in-time OI for both contracts")
                        switch = previous_oi.get(candidate, 0) > previous_oi.get(active, float("inf"))
                    if switch:
                        pending_candidate = candidate
            if pending_candidate is not None:
                candidate = pending_candidate
                paired = all(c in snapshot and snapshot[c].bar_state == "TRADED" and
                             snapshot[c].coverage_state != "UNKNOWN" for c in (active, candidate))
                if not paired and not self.config.defer_until_traded_pair:
                    raise ValueError("Roll needs synchronous old/new opens for executable gap accounting (traded bars only)")
                if paired:
                    old, new = snapshot[active], snapshot[candidate]
                    rollover = RollRecord(stamp, active, candidate, old.open, new.open,
                                          new.open - old.open, self.config.policy, self.config.adjustment)
                    if self.config.adjustment == "forward_additive":
                        offset = old.open * scale + offset - new.open * scale
                    elif self.config.adjustment == "forward_ratio":
                        if old.open <= 0 or new.open <= 0:
                            raise ValueError("Ratio adjustment requires positive roll prices")
                        scale *= old.open / new.open
                    else:
                        scale, offset = 1.0, 0.0
                    active = candidate
                    pending_candidate = None
                    self.records.append(rollover)
            if active not in snapshot:
                raise ValueError("Missing active-contract bar: " + active + " at " + stamp.isoformat())
            raw = snapshot[active]
            research = replace(raw, **{name: getattr(raw, name) * scale + offset for name in ("open", "high", "low", "close")})
            if active in (self.config.expirations or {}) and day > date.fromisoformat(self.config.expirations[active]):
                raise ValueError("Active contract is past declared expiration")
            yield SelectedBar(raw, research, rollover, scale, offset)
            for contract, bar in snapshot.items():
                totals[contract] = totals.get(contract, 0) + bar.volume
                if bar.coverage_state != "UNKNOWN":
                    coverage.setdefault(contract, set()).add(stamp)
                verified_oi = causal_open_interest(bar, stamp, _test_registry=self._test_registry)
                if verified_oi is not None:
                    oi[contract] = verified_oi
            last_day = day

        if pending_candidate is not None:
            raise ValueError("Requested roll never obtained a traded old/new pair")

def retrospective_back_adjust(selected, method="additive"):
    """Offline export ONLY: uses later rolls, never used by strategy/feature execution."""
    if method not in ("additive", "ratio"):
        raise ValueError("Unknown adjustment")
    result, offset, scale = [], 0.0, 1.0
    for item in reversed(selected):
        bar = item.raw
        result.append(replace(bar, **{key: getattr(bar, key) * scale + offset for key in ("open", "high", "low", "close")}))
        if item.roll:
            if method == "additive":
                offset += item.roll.price_difference
            else:
                if item.roll.old_open <= 0 or item.roll.new_open <= 0:
                    raise ValueError("Ratio adjustment requires positive prices")
                scale *= item.roll.new_open / item.roll.old_open
    return tuple(reversed(result))
