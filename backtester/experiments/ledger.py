"""Paired one-contract execution at exact, observed NQ open labels."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from backtester.instruments import instrument

from .inputs import MINUTE, Session, ticks
from .protocol import Protocol
from .rules import Decision


TICK_VALUE_CENTS = int(instrument("NQ").tick_value * 100)
Arm = Literal["candidate", "benchmark"]


@dataclass(frozen=True)
class Scenario:
    id: str
    delay_minutes: int
    adverse_ticks_per_side: int
    fee_cents: int

    def __post_init__(self):
        if any(type(value) is not int or value < 0 for value in
               (self.delay_minutes, self.adverse_ticks_per_side, self.fee_cents)):
            raise ValueError("Cost and timing inputs must be nonnegative integers")


def scenarios(protocol: Protocol) -> tuple[Scenario, ...]:
    costs = (
        ("gross", 0, 0),
        ("fee_only", 0, protocol.round_trip_fee_cents),
        ("base", 1, protocol.round_trip_fee_cents),
        ("stress", 2, protocol.round_trip_fee_cents),
        ("four_ticks", 4, protocol.round_trip_fee_cents),
    )
    return tuple(
        Scenario(prefix + name, delay, slippage, fee)
        for prefix, delay in (("", 0), ("delay_", protocol.delay_minutes))
        for name, slippage, fee in costs
    )


@dataclass(frozen=True)
class TradeRow:
    day: date
    contract: str
    arm: Arm
    scenario_id: str
    status: str
    reason: str
    event_label: datetime | None
    side: int | None
    scheduled_entry: datetime | None
    scheduled_exit: datetime | None
    actual_entry: datetime | None = None
    actual_exit: datetime | None = None
    entry_open_ticks: int | None = None
    exit_open_ticks: int | None = None
    entry_fill_ticks: int | None = None
    exit_fill_ticks: int | None = None
    quantity: int = 1
    tick_value_cents: int = TICK_VALUE_CENTS
    scheduled_fee_cents: int = 0
    adverse_ticks_per_side: int = 0
    gross_cents: int | None = None
    cost_cents: int | None = None
    net_cents: int | None = None
    break_even_ticks_per_side: float | None = None


@dataclass(frozen=True)
class SessionRow:
    day: date
    contract: str
    cash_open: datetime
    cash_close: datetime
    scenario_id: str
    decision_reason: str
    data_eligible: bool
    eligible: bool
    reason: str | None
    candidate_status: str
    benchmark_status: str
    candidate_gross_cents: int | None
    benchmark_gross_cents: int | None
    candidate_net_cents: int | None
    benchmark_net_cents: int | None
    uplift_cents: int | None


def simulate_round_trip(
    session: Session, protocol: Protocol, decision: Decision, arm: Arm, scenario: Scenario,
    *, coverage_reason: str | None,
) -> TradeRow:
    event = decision.event
    entry = event.decision_time + scenario.delay_minutes * MINUTE if event else None
    exit_label = entry + protocol.hold_minutes * MINUTE if entry is not None else None
    common = {
        "day": session.day, "contract": session.contract, "arm": arm, "scenario_id": scenario.id,
        "event_label": event.first_cross if event else None, "side": event.side if event else None,
        "scheduled_entry": entry, "scheduled_exit": exit_label,
        "scheduled_fee_cents": scenario.fee_cents, "adverse_ticks_per_side": scenario.adverse_ticks_per_side,
    }
    if event is None and decision.reason != "no_cross":
        return TradeRow(status="excluded", reason=decision.reason, **common)
    if event is None or (arm == "candidate" and not event.accepted):
        if coverage_reason:
            return TradeRow(status="excluded", reason=coverage_reason, **common)
        return TradeRow(status="abstained", reason=decision.reason, quantity=0,
                        gross_cents=0, cost_cents=0, net_cents=0, **common)
    if not session.cash_open <= entry < exit_label < session.cash_close:
        return TradeRow(status="excluded", reason="outside_cash_window", **common)
    if event.max_source_availability > entry:
        return TradeRow(status="excluded", reason="signal_unavailable_at_entry", **common)
    entry_bar = session.observations.get(entry)
    exit_bar = session.observations.get(exit_label)
    if entry_bar is None or not entry_bar.traded:
        return TradeRow(status="excluded", reason="invalid_exact_entry_open", **common)
    if exit_bar is None or not exit_bar.traded:
        return TradeRow(status="excluded", reason="invalid_exact_exit_open", **common)
    if coverage_reason:
        return TradeRow(status="excluded", reason=coverage_reason, **common)

    entry_ticks, exit_ticks = ticks(entry_bar.bar.open), ticks(exit_bar.bar.open)
    adverse = event.side * scenario.adverse_ticks_per_side
    entry_fill, exit_fill = entry_ticks + adverse, exit_ticks - adverse
    gross = event.side * (exit_ticks - entry_ticks) * TICK_VALUE_CENTS
    net = event.side * (exit_fill - entry_fill) * TICK_VALUE_CENTS - scenario.fee_cents
    cost = 2 * scenario.adverse_ticks_per_side * TICK_VALUE_CENTS + scenario.fee_cents
    if net != gross - cost:
        raise ArithmeticError("Execution and cost calculations do not reconcile")
    break_even = (gross - protocol.round_trip_fee_cents) / (2 * TICK_VALUE_CENTS)
    return TradeRow(
        status="filled", reason="scheduled_open_proxy", actual_entry=entry, actual_exit=exit_label,
        entry_open_ticks=entry_ticks, exit_open_ticks=exit_ticks,
        entry_fill_ticks=entry_fill, exit_fill_ticks=exit_fill,
        gross_cents=gross, cost_cents=cost, net_cents=net, break_even_ticks_per_side=break_even, **common,
    )


def pair_session(
    session: Session, protocol: Protocol, decision: Decision, scenario: Scenario, *,
    coverage_reason: str | None,
) -> tuple[SessionRow, tuple[TradeRow, TradeRow]]:
    candidate = simulate_round_trip(session, protocol, decision, "candidate", scenario,
                                    coverage_reason=coverage_reason)
    benchmark = simulate_round_trip(session, protocol, decision, "benchmark", scenario,
                                    coverage_reason=coverage_reason)
    reason = next((row.reason for row in (candidate, benchmark) if row.status == "excluded"), None)
    eligible = reason is None
    candidate_net = candidate.net_cents if eligible else None
    benchmark_net = benchmark.net_cents if eligible else None
    row = SessionRow(
        session.day, session.contract, session.cash_open, session.cash_close, scenario.id, decision.reason,
        coverage_reason is None and (decision.event is not None or decision.reason == "no_cross"),
        eligible, reason, candidate.status, benchmark.status,
        candidate.gross_cents if eligible else None, benchmark.gross_cents if eligible else None,
        candidate_net, benchmark_net, candidate_net - benchmark_net if eligible else None,
    )
    return row, (candidate, benchmark)
