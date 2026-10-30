"""Auditable bar fill approximations. No guaranteed fill on a limit touch."""
from dataclasses import dataclass
from enum import Enum
from math import floor, isfinite


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self):
        return 1 if self == Side.BUY else -1


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class Status(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class Ambiguity(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    OPTIMISTIC = "OPTIMISTIC"
    STOP_FIRST = "STOP_FIRST"
    TARGET_FIRST = "TARGET_FIRST"


@dataclass(frozen=True)
class ExecutionCosts:
    commission: float = 2.0
    exchange_fee: float = 1.0
    slippage_ticks: int = 1

    def __post_init__(self):
        if not all(isfinite(x) and x >= 0 for x in (self.commission, self.exchange_fee, self.slippage_ticks)):
            raise ValueError("Execution costs must be finite and nonnegative")
        if not isinstance(self.slippage_ticks, int):
            raise ValueError("Slippage must be whole ticks")

    def fee(self, quantity):
        return (self.commission + self.exchange_fee) * quantity

    def roundtrip(self, instrument):
        return 2 * (self.commission + self.exchange_fee + self.slippage_ticks * instrument.tick_value)


@dataclass(frozen=True)
class FillConfig:
    limit_mode: str = "trade_through"
    participation: object = None
    ambiguity: Ambiguity = Ambiguity.CONSERVATIVE

    def __post_init__(self):
        if self.limit_mode not in ("trade_through", "touch"):
            raise ValueError("Limit mode must be trade_through or touch")
        if self.participation is not None and not 0 < self.participation <= 1:
            raise ValueError("Participation must be in (0,1]")
        object.__setattr__(self, "ambiguity", Ambiguity(self.ambiguity))


@dataclass(frozen=True)
class OrderRequest:
    side: Side
    quantity: int = 1
    type: OrderType = OrderType.MARKET
    price: object = None
    stop_loss: object = None
    target: object = None
    tif: str = "DAY"
    reduce_only: bool = False
    reason: str = "strategy"

    def __post_init__(self):
        object.__setattr__(self, "side", Side(self.side))
        object.__setattr__(self, "type", OrderType(self.type))
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity <= 0:
            raise ValueError("Futures order quantity must be a positive integer")
        if self.type != OrderType.MARKET and self.price is None:
            raise ValueError("Limit/stop order price required")
        for p in (self.price, self.stop_loss, self.target):
            if p is not None and not isfinite(p):
                raise ValueError("Nonfinite order price")
        if self.tif not in ("DAY", "GTC"):
            raise ValueError("Unsupported time in force")


@dataclass
class Order:
    id: int
    submitted: object
    trading_date: object
    contract: str
    request: OrderRequest
    status: Status = Status.PENDING
    filled_quantity: int = 0
    triggered: bool = False
    fill_timestamp: object = None
    fill_price: object = None
    fees: float = 0.0
    slippage: float = 0.0
    rejection: object = None
    oco: object = None

    @property
    def remaining(self):
        return self.request.quantity - self.filled_quantity


@dataclass(frozen=True)
class Fill:
    order_id: int
    timestamp: object
    side: Side
    quantity: int
    reference_price: float
    price: float
    fees: float
    slippage: float
    intrabar: bool
    contract: str


class FillModel:
    def __init__(self, instrument, costs=None, config=None):
        self.instrument = instrument
        self.costs, self.config = costs or ExecutionCosts(), config or FillConfig()

    def capacity(self, bar):
        if bar.volume == 0:
            return 0
        return floor(bar.volume * self.config.participation) if self.config.participation is not None else 10**12

    def quote(self, order, bar):
        req = order.request
        if bar.bar_state != "TRADED" or bar.coverage_state == "UNKNOWN":
            return None
        if bar.timestamp < order.submitted or order.contract != bar.contract or order.remaining <= 0:
            return None
        slip = self.costs.slippage_ticks * self.instrument.tick_size
        intrabar = False
        if req.type == OrderType.MARKET or order.triggered:
            reference = bar.open
            price = reference + req.side.sign * slip
        elif req.type == OrderType.LIMIT:
            through = self.instrument.tick_size if self.config.limit_mode == "trade_through" else 0
            eligible = bar.low <= req.price - through if req.side == Side.BUY else bar.high >= req.price + through
            if not eligible:
                return None
            reference = req.price
            # Conservative execution at limit, no assumed price improvement; never violates limit.
            price = req.price
            intrabar = not (bar.open <= req.price if req.side == Side.BUY else bar.open >= req.price)
        else:
            eligible = bar.high >= req.price if req.side == Side.BUY else bar.low <= req.price
            if not eligible:
                return None
            reference = max(bar.open, req.price) if req.side == Side.BUY else min(bar.open, req.price)
            price = reference + req.side.sign * slip
            intrabar = reference != bar.open
        price = self.instrument.round_tick(price, "up" if req.side == Side.BUY else "down")
        return reference, price, intrabar

    def fill(self, order, bar, capacity):
        quote = self.quote(order, bar)
        if quote is None:
            return None
        if order.request.type == OrderType.STOP:
            order.triggered = True
        if capacity <= 0:
            return None
        reference, price, intrabar = quote
        quantity = min(order.remaining, capacity)
        if order.request.type == OrderType.STOP:
            order.triggered = True
        fill = Fill(order.id, bar.end if intrabar else bar.timestamp, order.request.side, quantity,
                    reference, price, self.costs.fee(quantity),
                    abs(price - reference) * self.instrument.point_value * quantity,
                    intrabar, bar.contract)
        order.filled_quantity += quantity
        order.status = Status.FILLED if order.remaining == 0 else Status.PARTIALLY_FILLED
        order.fill_timestamp, order.fill_price = fill.timestamp, price
        order.fees += fill.fees
        order.slippage += fill.slippage
        return fill

    def choose_bracket(self, stop, target, bar):
        stop_quote, target_quote = self.quote(stop, bar), self.quote(target, bar)
        if stop_quote is not None and target_quote is not None:
            # An opening gap resolves the order of events without OHLC path speculation.
            if not stop_quote[2]:
                return stop, False
            if not target_quote[2]:
                return target, False
            use_stop = self.config.ambiguity in (Ambiguity.CONSERVATIVE, Ambiguity.STOP_FIRST)
            return (stop if use_stop else target), True
        return (stop if stop_quote is not None else target if target_quote is not None else None), False
