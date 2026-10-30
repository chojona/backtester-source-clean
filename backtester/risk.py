"""Entry risk constraints; protective exits remain permitted."""
from dataclasses import dataclass
from datetime import time
from math import floor, isfinite
from .sessions import NY


def risk_per_contract(entry, stop, instrument, costs):
    return abs(entry - stop) * instrument.point_value + costs.roundtrip(instrument)


def size_fixed(contracts, maximum):
    if not isinstance(contracts, int) or not isinstance(maximum, int) or contracts <= 0 or maximum <= 0:
        raise ValueError("Contract sizing requires positive integers")
    return min(contracts, maximum)


def size_dollar_risk(dollars, entry, stop, instrument, costs, maximum):
    if not isfinite(dollars) or dollars <= 0 or isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
        raise ValueError("Risk dollars and maximum contracts must be positive")
    per = risk_per_contract(entry, stop, instrument, costs)
    if per <= 0:
        raise ValueError("Risk per contract must be positive")
    return min(floor(dollars / per), maximum)


@dataclass(frozen=True)
class RiskConfig:
    max_risk_per_trade: float = 1000
    max_daily_loss: float = 2000
    max_trades_per_day: int = 10
    max_simultaneous_positions: int = 1
    max_contracts: int = 10
    trading_start: str = "09:30"
    trading_cutoff: str = "15:55"
    margin_per_contract: float = 15000

    def __post_init__(self):
        for value in (self.max_risk_per_trade, self.max_daily_loss, self.margin_per_contract):
            if not isfinite(value) or value <= 0:
                raise ValueError("Risk and margin limits must be finite and positive")
        for value in (self.max_trades_per_day, self.max_simultaneous_positions, self.max_contracts):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("Risk counts must be positive integers")
        if self.max_simultaneous_positions != 1:
            raise ValueError("Initial engine supports one instrument and one position per run")
        if not time.fromisoformat(self.trading_start) < time.fromisoformat(self.trading_cutoff):
            raise ValueError("Trading start must precede cutoff")


class RiskManager:
    def __init__(self, config):
        self.config = config
        self.day, self.start_equity, self.entries, self.locked = None, None, 0, False

    def observe(self, trading_date, equity):
        if trading_date != self.day:
            self.day, self.start_equity, self.entries, self.locked = trading_date, equity, 0, False
        if equity - self.start_equity <= -self.config.max_daily_loss:
            self.locked = True

    def entry_rejection(self, request, fill_price, stamp, equity, instrument, costs, position=False):
        cfg = self.config
        if self.locked:
            return "daily_loss_lockout"
        clock = stamp.astimezone(NY).time()
        if not time.fromisoformat(cfg.trading_start) <= clock < time.fromisoformat(cfg.trading_cutoff):
            return "outside_entry_window"
        if position:
            return "position_already_open"
        if self.entries >= cfg.max_trades_per_day:
            return "max_trades_per_day"
        if request.quantity > cfg.max_contracts:
            return "max_contracts"
        if request.stop_loss is None:
            return "entry_requires_stop_for_risk_measurement"
        distance = (fill_price - request.stop_loss) * request.side.sign
        if distance <= 0:
            return "stop_on_wrong_side_or_gap_beyond_stop"
        risk = risk_per_contract(fill_price, request.stop_loss, instrument, costs) * request.quantity
        if risk > cfg.max_risk_per_trade:
            return "max_risk_per_trade"
        entry_cost = costs.fee(request.quantity) + costs.slippage_ticks * instrument.tick_value * request.quantity
        if equity - entry_cost < request.quantity * cfg.margin_per_contract:
            return "insufficient_margin"
        if request.target is not None and (request.target - fill_price) * request.side.sign <= 0:
            return "target_on_wrong_side_or_gap_beyond_target"
        return None
