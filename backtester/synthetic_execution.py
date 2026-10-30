"""Deterministic, synthetic-only, single-contract market-order simulator.

No strategy or label code is imported. A completed bar is observed at ``bar.end``;
close, decision, submission, and the next bar's open are ordered event phases
when their timestamps coincide. The source bar can never fill its own order.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite

from .data import Bar, validate
from .execution import Side, Status


@dataclass(frozen=True)
class Target:
    observation_at: datetime
    decision_at: datetime
    submitted_at: datetime
    target_contracts: int
    stop_price: float | None = None


@dataclass(frozen=True)
class InstrumentSpec:
    """USD futures, integer contracts, price points and per-side USD commissions."""
    symbol: str
    quantity_unit: str
    tick_size: float
    tick_value: float
    contract_multiplier: float
    cost_convention: str = "adverse_points_and_per_side_usd"

    @classmethod
    def from_instrument(cls, instrument):
        return cls(instrument.symbol, "contracts", instrument.tick_size,
                   instrument.tick_value, instrument.point_value)

    def __post_init__(self):
        if self.quantity_unit != "contracts" or self.cost_convention != "adverse_points_and_per_side_usd":
            raise ValueError("Unsupported instrument or cost convention")
        if any(not isfinite(x) or x <= 0 for x in
               (self.tick_size, self.tick_value, self.contract_multiplier)):
            raise ValueError("Instrument values must be positive and finite")
        if abs(self.tick_size * self.contract_multiplier - self.tick_value) > 1e-8:
            raise ValueError("Tick value must equal tick size times multiplier")


@dataclass(frozen=True)
class Config:
    initial_cash: float = 100_000.0
    max_exposure: int = 1
    spread_points: float = 0.0
    slippage_points: float = 0.0
    commission_per_contract: float = 0.0
    instrument_spec: InstrumentSpec | None = None
    max_position_size: int | None = None
    max_gross_notional: float | None = None
    max_trade_risk: float | None = None
    max_daily_loss: float | None = None
    max_session_loss: float | None = None
    max_buying_power_multiple: float | None = None

    def __post_init__(self):
        if not isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("Initial cash must be positive and finite")
        if type(self.max_exposure) is not int or self.max_exposure < 1:
            raise ValueError("Maximum exposure must be a positive integer")
        if any(not isfinite(x) or x < 0 for x in
               (self.spread_points, self.slippage_points, self.commission_per_contract)):
            raise ValueError("Costs must be finite and nonnegative")
        if self.max_position_size is not None and (type(self.max_position_size) is not int or self.max_position_size < 1):
            raise ValueError("Maximum position size must be a positive integer")
        for limit in (self.max_gross_notional, self.max_trade_risk, self.max_daily_loss,
                      self.max_session_loss, self.max_buying_power_multiple):
            if limit is not None and (not isfinite(limit) or limit <= 0):
                raise ValueError("Risk limits must be positive and finite")


@dataclass
class _Lot:
    direction: int
    quantity: int
    entry_reference: float
    entry_price: float
    entry_time: datetime
    entry_fee_unit: float
    entry_spread_unit: float
    entry_slippage_unit: float


@dataclass
class Result:
    orders: list = field(default_factory=list)
    fills: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    risk_events: list = field(default_factory=list)
    order_events: list = field(default_factory=list)


def _stamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("All event timestamps must be timezone aware")
    return value


def _transition(result, order, status, reason, at):
    order["status"], order["reason"] = status.value, reason
    result.order_events.append(dict(order_id=order["id"], at=at,
                                    status=status.value, reason=reason))
    if status == Status.REJECTED:
        result.risk_events.append(dict(order_id=order["id"], at=at, reason=reason))


def _opening_equity(cash, lots, open_price, multiplier):
    return cash + sum(lot.direction * (open_price - lot.entry_price) *
                      lot.quantity * multiplier for lot in lots)


def simulate(bars, targets, calendar, instrument, config=Config()):
    """Execute absolute signed contract targets at the next eligible observed open.

    A missing in-session bar rejects a pending order. A session/market closure
    expires it. No order carries across a closure or contract change. Missing
    marks retain the last observed equity; the next observed mark includes any gap.
    """
    bars, targets = tuple(bars), tuple(targets)
    if not bars or any(not isinstance(b, Bar) for b in bars):
        raise ValueError("Nonempty validated Bar input required")
    integrity = validate(bars, calendar)
    if integrity.off_tick_prices:
        raise ValueError("Off-tick synthetic bar price")
    spec = config.instrument_spec or InstrumentSpec.from_instrument(instrument)
    if (spec.symbol != instrument.symbol or spec.tick_size != instrument.tick_size or
            spec.tick_value != instrument.tick_value or
            spec.contract_multiplier != instrument.point_value):
        raise ValueError("Instrument specification differs from bar instrument")
    if len({b.contract for b in bars}) != 1 or bars[0].symbol != instrument.symbol:
        raise ValueError("One dated contract matching the instrument is required")
    if any(b.provider != "SYNTHETIC" or b.dataset != "STEP7A_SYNTHETIC" for b in bars):
        raise ValueError("Step 7A accepts only explicitly marked synthetic bars")
    if any(b.bar_state != "TRADED" or b.coverage_state == "UNKNOWN" or b.volume <= 0 or
           min(b.open, b.high, b.low, b.close) <= 0 for b in bars):
        raise ValueError("Only positive, traded bars with known-or-unverified coverage are supported")
    if any(b.duration != bars[0].duration for b in bars):
        raise ValueError("Mixed bar durations are unsupported")
    ends = {b.end: i for i, b in enumerate(bars)}
    if len(ends) != len(bars):
        raise ValueError("Ambiguous observation endpoints")
    scheduled = {}
    result = Result()
    for number, target in enumerate(targets, 1):
        if not isinstance(target, Target):
            raise TypeError("Targets must be Target records")
        observed, decided, submitted = map(_stamp, (target.observation_at, target.decision_at, target.submitted_at))
        if not observed <= decided <= submitted:
            raise ValueError("Observation, decision, submission ordering is invalid")
        if type(target.target_contracts) is not int:
            raise ValueError("Target contracts must be an integer")
        if target.stop_price is not None and (not isfinite(target.stop_price) or target.stop_price <= 0):
            raise ValueError("Stop price must be positive and finite")
        index = ends.get(observed)
        if index is None:
            order = dict(id=number, observation_at=observed, decision_at=decided,
                                      submitted_at=submitted, target_contracts=target.target_contracts,
                                      stop_price=target.stop_price,
                                      status=Status.PENDING.value, reason=None, fill_at=None)
            result.orders.append(order)
            _transition(result, order, Status.REJECTED, "missing_observation", submitted)
            continue
        if index in scheduled:
            raise ValueError("Multiple targets from one observation are ambiguous")
        scheduled[index] = (number, target)
    position = 0
    lots = []
    cash = config.initial_cash
    realized_gross = 0.0
    commission_total = spread_total = slippage_total = 0.0
    turnover = 0.0
    peak = config.initial_cash
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    pending = None
    previous = None
    day_key = session_key = None
    day_start = session_start = None
    day_locked = session_locked = False
    for index, bar in enumerate(bars):
        session = calendar.classify(bar.timestamp)
        opening_equity = _opening_equity(cash, lots, bar.open, spec.contract_multiplier)
        if session.trading_date != day_key:
            baseline = result.equity_curve[-1]["equity"] if result.equity_curve else opening_equity
            day_key, day_start, day_locked = session.trading_date, baseline, False
        current_session = (session.trading_date, session.session)
        if current_session != session_key:
            baseline = result.equity_curve[-1]["equity"] if result.equity_curve else opening_equity
            session_key, session_start, session_locked = current_session, baseline, False
        if config.max_daily_loss is not None and opening_equity <= day_start - config.max_daily_loss:
            if not day_locked:
                result.risk_events.append(dict(order_id=None, at=bar.timestamp, reason="daily_loss_lockout"))
            day_locked = True
        if config.max_session_loss is not None and opening_equity <= session_start - config.max_session_loss:
            if not session_locked:
                result.risk_events.append(dict(order_id=None, at=bar.timestamp, reason="session_loss_lockout"))
            session_locked = True
        if previous and pending:
            prior_session = calendar.classify(previous.timestamp)
            if session.trading_date != prior_session.trading_date or session.session != prior_session.session:
                _transition(result, pending, Status.EXPIRED, "market_closure", bar.timestamp)
                pending = None
            elif bar.timestamp != previous.end:
                _transition(result, pending, Status.REJECTED, "missing_bar", bar.timestamp)
                pending = None
        if pending and bar.timestamp >= pending["submitted_at"]:
            # Equality is valid only for adjacent close/open event phases.
            if bar.timestamp == pending["submitted_at"] and (not previous or previous.end != bar.timestamp):
                raise ValueError("Ambiguous simultaneous submission and open")
            change = pending["target_contracts"] - position
            target = pending["target_contracts"]
            increases = target != 0 and (position == 0 or target * position < 0 or abs(target) > abs(position))
            side = Side.BUY if change > 0 else Side.SELL
            quantity = abs(change)
            half_spread = config.spread_points / 2
            spread_price = instrument.round_tick(bar.open + side.sign * half_spread,
                                                  "up" if side == Side.BUY else "down")
            price = instrument.round_tick(spread_price + side.sign * config.slippage_points,
                                          "up" if side == Side.BUY else "down")
            spread_unit = abs(spread_price - bar.open) * spec.contract_multiplier
            slippage_unit = abs(price - spread_price) * spec.contract_multiplier
            reason = None
            if abs(target) > config.max_exposure:
                reason = "max_exposure"
            elif config.max_position_size is not None and abs(target) > config.max_position_size:
                reason = "max_position_size"
            elif change != 0 and price <= 0:
                reason = "invalid_fill_price"
            elif increases and day_locked:
                reason = "daily_loss_lockout"
            elif increases and session_locked:
                reason = "session_loss_lockout"
            elif increases and config.max_gross_notional is not None and abs(target) * bar.open * spec.contract_multiplier > config.max_gross_notional:
                reason = "max_gross_notional"
            elif increases and config.max_buying_power_multiple is not None and (
                    opening_equity <= 0 or abs(target) * bar.open * spec.contract_multiplier >
                    opening_equity * config.max_buying_power_multiple):
                reason = "insufficient_buying_power"
            elif increases and config.max_trade_risk is not None:
                stop = pending["stop_price"]
                entry_quantity = abs(target) if position * target <= 0 else abs(target) - abs(position)
                if stop is None:
                    reason = "entry_requires_stop_for_risk_measurement"
                elif (price - stop) * side.sign <= 0:
                    reason = "stop_on_wrong_side_or_gap_beyond_stop"
                else:
                    exit_mode = "down" if side == Side.BUY else "up"
                    hypothetical_exit = instrument.round_tick(
                        instrument.round_tick(stop - side.sign * half_spread, exit_mode)
                        - side.sign * config.slippage_points, exit_mode)
                    if hypothetical_exit <= 0:
                        reason = "invalid_stop_exit_price"
                    elif entry_quantity * (abs(price - hypothetical_exit) * spec.contract_multiplier +
                                         2 * config.commission_per_contract) > config.max_trade_risk:
                        reason = "max_trade_risk"
            if reason:
                _transition(result, pending, Status.REJECTED, reason, bar.timestamp)
            elif change == 0:
                _transition(result, pending, Status.CANCELLED, "already_at_target", bar.timestamp)
            else:
                fee = quantity * config.commission_per_contract
                cash -= fee
                commission_total += fee
                spread_total += quantity * spread_unit
                slippage_total += quantity * slippage_unit
                turnover += quantity * bar.open * spec.contract_multiplier
                fill = dict(order_id=pending["id"], observation_at=pending["observation_at"],
                            decision_at=pending["decision_at"], submitted_at=pending["submitted_at"],
                            fill_at=bar.timestamp, side=side.value, quantity=quantity,
                            reference_price=bar.open, price=price, commission=fee,
                            spread_cost=quantity * spread_unit,
                            slippage_cost=quantity * slippage_unit)
                result.fills.append(fill)
                pending["fill_at"] = bar.timestamp
                _transition(result, pending, Status.FILLED, None, bar.timestamp)
                remaining = quantity
                while remaining and lots and lots[0].direction != side.sign:
                    lot = lots[0]
                    closed = min(remaining, lot.quantity)
                    gross = lot.direction * (bar.open - lot.entry_reference) * closed * spec.contract_multiplier
                    impact = closed * (lot.entry_spread_unit + spread_unit + lot.entry_slippage_unit + slippage_unit)
                    fees = closed * (lot.entry_fee_unit + config.commission_per_contract)
                    net = gross - impact - fees
                    realized_gross += gross
                    cash += lot.direction * (price - lot.entry_price) * closed * spec.contract_multiplier
                    result.trades.append(dict(entry_at=lot.entry_time, exit_at=bar.timestamp,
                        direction="long" if lot.direction == 1 else "short", quantity=closed,
                        entry_reference=lot.entry_reference, exit_reference=bar.open,
                        entry_price=lot.entry_price, exit_price=price, gross_pnl=gross,
                        spread_cost=closed * (lot.entry_spread_unit + spread_unit),
                        slippage_cost=closed * (lot.entry_slippage_unit + slippage_unit),
                        commission=fees, net_pnl=net))
                    lot.quantity -= closed
                    remaining -= closed
                    if lot.quantity == 0:
                        lots.pop(0)
                if remaining:
                    lots.append(_Lot(side.sign, remaining, bar.open, price, bar.timestamp,
                                     config.commission_per_contract, spread_unit, slippage_unit))
                position += change
                if position != sum(lot.direction * lot.quantity for lot in lots) or abs(position) > config.max_exposure:
                    raise AssertionError("Post-fill position invariant failed")
            pending = None
        # Mark after the open fill at the completed bar close.
        unrealized = sum(lot.direction * (bar.close - lot.entry_price) * lot.quantity * spec.contract_multiplier for lot in lots)
        gross_unrealized = sum(lot.direction * (bar.close - lot.entry_reference) * lot.quantity * spec.contract_multiplier for lot in lots)
        equity = cash + unrealized
        gross_equity = config.initial_cash + realized_gross + gross_unrealized
        peak = max(peak, equity)
        drawdown = peak - equity
        max_drawdown = max(max_drawdown, drawdown)
        max_drawdown_pct = max(max_drawdown_pct, drawdown / peak)
        result.equity_curve.append(dict(timestamp=bar.end, cash=cash,
            realized_pnl=cash - config.initial_cash, unrealized_pnl=unrealized,
            equity=equity, gross_equity=gross_equity, position=position,
            gross_return=(gross_equity / config.initial_cash - 1),
            net_return=(equity / config.initial_cash - 1),
            cumulative_commission=commission_total, cumulative_spread_cost=spread_total,
            cumulative_slippage_cost=slippage_total, peak_equity=peak,
            drawdown=drawdown, drawdown_pct=drawdown / peak,
            exposure=abs(position) / config.max_exposure))
        if index in scheduled:
            if pending:
                _transition(result, pending, Status.CANCELLED, "superseded", bar.end)
                pending = None
            number, target = scheduled[index]
            order = dict(id=number, observation_at=target.observation_at,
                         decision_at=target.decision_at, submitted_at=target.submitted_at,
                         target_contracts=target.target_contracts, stop_price=target.stop_price,
                         status=Status.PENDING.value,
                         reason=None, fill_at=None)
            result.orders.append(order)
            _transition(result, order, Status.PENDING, None, bar.end)
            if target.submitted_at < bar.end:
                raise ValueError("Submission precedes completed observation")
            pending = order
        previous = bar
    if pending:
        _transition(result, pending, Status.EXPIRED, "dataset_end", bars[-1].end)
    final = result.equity_curve[-1]
    result.summary = dict(initial_cash=config.initial_cash, final_cash=cash,
        final_equity=final["equity"], realized_pnl=final["realized_pnl"],
        unrealized_pnl=final["unrealized_pnl"], gross_pnl=final["gross_equity"]-config.initial_cash,
        net_pnl=final["equity"]-config.initial_cash, gross_return=final["gross_return"],
        net_return=final["net_return"], commission=commission_total,
        spread_cost=spread_total, slippage_cost=slippage_total,
        total_cost=commission_total+spread_total+slippage_total,
        turnover_notional=turnover, turnover_ratio=turnover/config.initial_cash,
        mean_exposure=sum(row["exposure"] for row in result.equity_curve)/len(result.equity_curve),
        max_drawdown=max_drawdown, max_drawdown_pct=max_drawdown_pct,
        final_position=position, fills=len(result.fills), closed_trades=len(result.trades))
    return result
