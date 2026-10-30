"""Single-position futures accounting. Reference P&L separates costs from fills."""
from dataclasses import dataclass, field


@dataclass
class Position:
    instrument: str
    contract: str
    direction: int
    contracts: int
    initial_contracts: int
    entry_time: object
    entry_price: float
    entry_reference: float
    entry_order: int
    stop: float
    target: object
    initial_risk: float
    session: str
    trading_date: object
    fees: float
    slippage: float
    mfe_points: float = 0.0
    mae_points: float = 0.0
    exited: int = 0
    exit_notional: float = 0.0
    exit_reference_notional: float = 0.0
    last_exit: object = None
    exit_reason: str = ""

    def excursion(self, price):
        change = self.direction * (price - self.entry_price)
        self.mfe_points = max(self.mfe_points, change)
        self.mae_points = min(self.mae_points, change)


class Portfolio:
    def __init__(self, instrument, cash=100000):
        from math import isfinite
        if not isfinite(cash) or cash <= 0:
            raise ValueError("Initial cash must be finite and positive")
        self.instrument, self.initial_cash, self.balance = instrument, cash, cash
        self.position = None
        self.trades, self.equity_curve, self.trade_equity = [], [], []
        self.peak = cash

    def equity(self, price):
        p = self.position
        return self.balance + (p.direction * (price - p.entry_price) * p.contracts * self.instrument.point_value if p else 0)

    def open(self, fill, request, info, risk):
        if self.position:
            raise ValueError("Scale-in and hedged positions are not supported")
        self.balance -= fill.fees
        self.position = Position(self.instrument.symbol, fill.contract, fill.side.sign,
            fill.quantity, fill.quantity, fill.timestamp, fill.price, fill.reference_price,
            fill.order_id, request.stop_loss, request.target, risk,
            info.session, info.trading_date, fill.fees, fill.slippage)

    def close(self, fill, strategy, reason):
        p = self.position
        if not p or fill.side.sign != -p.direction or fill.quantity > p.contracts:
            raise ValueError("Exit cannot reverse or exceed current position")
        self.balance += p.direction * (fill.price - p.entry_price) * fill.quantity * self.instrument.point_value - fill.fees
        p.excursion(fill.price)
        p.contracts -= fill.quantity
        p.exited += fill.quantity
        p.exit_notional += fill.price * fill.quantity
        p.exit_reference_notional += fill.reference_price * fill.quantity
        p.fees += fill.fees
        p.slippage += fill.slippage
        p.last_exit, p.exit_reason = fill.timestamp, reason
        if p.contracts:
            return None
        exit_price = p.exit_notional / p.exited
        exit_reference = p.exit_reference_notional / p.exited
        gross = p.direction * (exit_reference - p.entry_reference) * p.initial_contracts * self.instrument.point_value
        net = gross - p.fees - p.slippage
        trade = dict(entry_time=p.entry_time, exit_time=p.last_exit,
            direction="long" if p.direction == 1 else "short",
            entry_price=p.entry_price, exit_price=exit_price,
            entry_reference=p.entry_reference, exit_reference=exit_reference,
            contracts=p.initial_contracts, gross_pnl=gross, fees=p.fees, slippage=p.slippage,
            net_pnl=net, initial_risk=p.initial_risk,
            r_multiple=net / p.initial_risk if p.initial_risk else None,
            mfe_points=p.mfe_points, mae_points=-p.mae_points,
            mfe_dollars=p.mfe_points * p.initial_contracts * self.instrument.point_value,
            mae_dollars=-p.mae_points * p.initial_contracts * self.instrument.point_value,
            holding_seconds=(p.last_exit - p.entry_time).total_seconds(),
            session=p.session, trading_date=p.trading_date,
            instrument=p.instrument, contract=p.contract, strategy=strategy,
            exit_reason=reason, excursion_basis="complete_held_bars_plus_fills")
        self.trades.append(trade)
        self.position = None
        row = self.record(fill.timestamp, fill.price, "trade")
        self.trade_equity.append(dict(row))
        return trade

    def record(self, stamp, price, event="bar_close"):
        equity = self.equity(price)
        self.peak = max(self.peak, equity)
        row = dict(timestamp=stamp, event=event, equity=equity, peak_equity=self.peak,
                   drawdown_dollars=self.peak - equity,
                   drawdown_percentage=(self.peak - equity) / self.peak,
                   balance=self.balance, contracts=self.position.contracts if self.position else 0)
        self.equity_curve.append(row)
        return row
