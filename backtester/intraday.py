"""Chronological engine: fill old orders, mark account, compute features, call strategy."""
from dataclasses import asdict, replace
from .execution import Order, OrderRequest, Side, OrderType, Status, FillModel
from .features import FeatureEngine
from .portfolio import Portfolio
from .risk import RiskManager, RiskConfig, risk_per_contract
from .strategy import StrategyContext, frozen_mapping

ACTIVE = (Status.PENDING, Status.PARTIALLY_FILLED)


class IntradayEngine:
    def __init__(self, instrument, calendar, strategy, cash=100000, costs=None,
                 fills=None, risk=None, feature_config=None, roll_position_policy="flatten"):
        if roll_position_policy not in ("flatten", "reopen"):
            raise ValueError("Unknown roll position policy")
        self.instrument, self.calendar, self.strategy = instrument, calendar, strategy
        self.features = FeatureEngine(calendar, **(feature_config or {}))
        self.model = FillModel(instrument, costs, fills)
        self.portfolio = Portfolio(instrument, cash)
        self.risk = RiskManager(risk or RiskConfig())
        self.roll_position_policy = roll_position_policy
        self.orders, self.fills, self.feature_rows = [], [], []
        self.ambiguous_bars, self.warnings = [], []
        self.history = []
        self.context = None
        self.last_day = None
        self._has_run = False

    def submit(self, request, timestamp, info, contract, oco=None):
        # Explicit rounding is avoided: a wrong order price is rejected, not silently changed.
        order = Order(len(self.orders) + 1, timestamp, info.trading_date, contract, request, oco=oco)
        self.orders.append(order)
        for value in (request.price, request.stop_loss, request.target):
            if value is not None and abs(self.instrument.round_tick(value) - value) > 1e-8:
                order.status, order.rejection = Status.REJECTED, "off_tick_order_price"
        return order

    def submit_requests(self, requests, context):
        for request in requests or ():
            if not isinstance(request, OrderRequest):
                raise TypeError("Strategies return OrderRequest instances")
            self.submit(request, context.timestamp, self.calendar.classify(context.bar.timestamp), context.bar.contract)

    def cancel_exits(self, exclude=None):
        for order in self.orders:
            if order.request.reduce_only and order.id != exclude and order.status in ACTIVE:
                order.status = Status.CANCELLED

    def brackets(self, entry, bar, info):
        p = self.portfolio.position
        side = Side.SELL if p.direction == 1 else Side.BUY
        # Market-at-open entries can have same-bar protective fills. Intrabar entries handled conservatively below.
        submitted = bar.timestamp if not entry.intrabar else bar.end
        self.submit(OrderRequest(side, p.contracts, OrderType.STOP, price=p.stop,
                                 tif="GTC", reduce_only=True, reason="stop_loss"), submitted, info, bar.contract, p.entry_order)
        if p.target is not None:
            self.submit(OrderRequest(side, p.contracts, OrderType.LIMIT, price=p.target,
                                     tif="GTC", reduce_only=True, reason="target"), submitted, info, bar.contract, p.entry_order)

    def reject(self, order, reason):
        order.status, order.rejection = Status.REJECTED, reason

    def execute(self, order, bar, info, capacity):
        quote = self.model.quote(order, bar)
        if quote is None:
            return capacity, None
        p = self.portfolio.position
        if order.request.reduce_only:
            if not p or order.request.side.sign != -p.direction:
                self.reject(order, "no_matching_position")
                return capacity, None
            if order.remaining > p.contracts:
                order.request = replace(order.request, quantity=order.filled_quantity + p.contracts)
        else:
            reason = self.risk.entry_rejection(order.request, quote[1], bar.timestamp,
                      self.portfolio.equity(bar.open), self.instrument, self.model.costs, bool(p))
            if reason:
                self.reject(order, reason)
                return capacity, None
        fill = self.model.fill(order, bar, capacity)
        if fill is None:
            return capacity, None
        self.fills.append(fill)
        if order.request.reduce_only:
            self.portfolio.close(fill, self.strategy.name, order.request.reason)
            # Once an exit is selected, cancel competing exits even if it only partially filled.
            if self.portfolio.position is None or order.request.type == OrderType.STOP:
                self.cancel_exits(exclude=order.id)
            else:
                # Partial targets retain their protective stop for the residual contracts.
                for sibling in self.orders:
                    if sibling.oco == order.oco and sibling.id != order.id and sibling.status in ACTIVE:
                        sibling.request = replace(sibling.request, quantity=sibling.filled_quantity + self.portfolio.position.contracts)
        else:
            actual_request = replace(order.request, quantity=fill.quantity)
            risk = risk_per_contract(fill.price, actual_request.stop_loss, self.instrument, self.model.costs) * fill.quantity
            self.portfolio.open(fill, actual_request, info, risk)
            self.risk.entries += 1
            if order.remaining:
                order.status = Status.CANCELLED
                order.rejection = "partial_entry_remainder_cancelled; scale-in unsupported"
            self.brackets(fill, bar, info)
        self.risk.observe(info.trading_date, self.portfolio.equity(fill.price))
        return capacity - fill.quantity, fill

    def handle_roll(self, item, info):
        bar, record = item.raw, item.roll
        for order in self.orders:
            if order.status in ACTIVE:
                order.status = Status.CANCELLED
                order.rejection = "contract_roll"
        p = self.portfolio.position
        if p is None:
            return
        side = Side.SELL if p.direction == 1 else Side.BUY
        old_bar = replace(bar, contract=record.old_contract, open=record.old_open,
                          high=record.old_open, low=record.old_open, close=record.old_open)
        quantity, stop, target, direction = p.contracts, p.stop, p.target, p.direction
        order = self.submit(OrderRequest(side, quantity, reduce_only=True, reason="contract_roll"),
                            bar.timestamp, info, record.old_contract)
        # Roll legs require paired executable opens. Bar-level participation is unknown for old contract;
        # explicit roll fills model unlimited liquidity and record this approximation.
        self.warnings.append("Roll fills use synchronous opens and do not apply participation capacity")
        self.execute(order, old_bar, info, quantity)
        if self.roll_position_policy == "reopen":
            gap = record.price_difference
            request = OrderRequest(Side.BUY if direction == 1 else Side.SELL, quantity,
                stop_loss=self.instrument.round_tick(stop + gap),
                target=self.instrument.round_tick(target + gap) if target is not None else None,
                reason="roll_reopen")
            order = self.submit(request, bar.timestamp, info, bar.contract)
            self.execute(order, bar, info, quantity)

    def make_context(self, item, values):
        p = self.portfolio.position
        position = frozen_mapping(asdict(p)) if p else None
        orders = tuple(frozen_mapping(dict(id=o.id, status=o.status.value,
                      side=o.request.side.value, quantity=o.request.quantity, filled=o.filled_quantity,
                      type=o.request.type.value, price=o.request.price)) for o in self.orders)
        return StrategyContext(item.raw.end, item.research, tuple(self.history), values, position,
            frozen_mapping(dict(balance=self.portfolio.balance, equity=self.portfolio.equity(item.raw.close),
                                daily_loss_locked=self.risk.locked, raw_close=item.raw.close,
                                active_contract=item.raw.contract, research_scale=item.scale,
                                research_offset=item.offset)), orders)

    def run(self, selected):
        if self._has_run:
            raise ValueError("Engine instances are single-run; create a fresh instance for reproducibility")
        self._has_run = True
        previous_bar = None
        for item in selected:
            bar = item.raw
            if bar.symbol != self.instrument.symbol:
                raise ValueError("Mixed instruments in a single run")
            if previous_bar and bar.timestamp < previous_bar.end:
                raise ValueError("Active bars must be chronological and non-overlapping")
            if previous_bar and bar.contract != previous_bar.contract and not item.roll:
                raise ValueError("Active contract changed without an explicit roll record")
            if item.research.timestamp != bar.timestamp or item.research.end != bar.end or item.research.contract != bar.contract:
                raise ValueError("Research and executable bars must identify the same interval and contract")
            if (self.features.ib_minutes * 60) % bar.duration.total_seconds():
                raise ValueError("Initial Balance window must align to bar duration")
            previous_bar = bar
            info = self.calendar.classify(bar.timestamp)
            if info is None or not self.calendar.valid_bar(bar.timestamp, bar.duration):
                raise ValueError("Invalid active bar session")
            if self.last_day != info.trading_date:
                if self.context:
                    self.submit_requests(self.strategy.on_session_end(replace(self.context, boundary_reason="trading_date_end")), self.context)
                baseline = self.portfolio.equity_curve[-1]["equity"] if self.portfolio.equity_curve else self.portfolio.initial_cash
                self.risk.observe(info.trading_date, baseline)
            if item.roll:
                self.handle_roll(item, info)
            self.risk.observe(info.trading_date, self.portfolio.equity(bar.open))
            p_start = self.portfolio.position
            capacity = self.model.capacity(bar)
            fills_before = len(self.fills)
            # Existing discretionary orders run first; protective exits take priority over new entries.
            active = [o for o in self.orders if o.status in ACTIVE]
            active.sort(key=lambda o: not o.request.reduce_only)
            for order in active:
                if order.status not in ACTIVE:
                    continue
                if order.request.tif == "DAY" and order.trading_date != info.trading_date:
                    order.status = Status.EXPIRED
                    continue
                if order.oco is not None:
                    continue
                capacity, _ = self.execute(order, bar, info, capacity)
            p = self.portfolio.position
            if p:
                siblings = [o for o in self.orders if o.oco == p.entry_order and o.status in ACTIVE]
                stop = next((o for o in siblings if o.request.type == OrderType.STOP), None)
                target = next((o for o in siblings if o.request.type == OrderType.LIMIT), None)
                chosen, ambiguous = self.model.choose_bracket(stop, target, bar) if stop and target else (stop or target, False)
                # Intrabar entry: path before entry is unknown. A same-bar stop is an adverse possibility;
                # targets wait until the following bar, avoiding a silently favorable assumed path.
                entry_fill = next((f for f in self.fills[fills_before:] if f.order_id == p.entry_order), None)
                if entry_fill and entry_fill.intrabar and p.stop is not None:
                    adverse = bar.low <= p.stop if p.direction == 1 else bar.high >= p.stop
                    target_possible = target is not None and self.model.quote(replace(target, submitted=bar.timestamp), bar) is not None
                    prefer_target = self.model.config.ambiguity.value in ("OPTIMISTIC", "TARGET_FIRST")
                    if target_possible and prefer_target and target:
                        target.submitted = bar.timestamp
                        chosen, ambiguous = target, True
                    elif adverse and stop:
                        stop.submitted = bar.timestamp
                        chosen, ambiguous = stop, True
                if ambiguous:
                    self.ambiguous_bars.append(dict(timestamp=bar.timestamp, contract=bar.contract,
                        policy=self.model.config.ambiguity.value, reason="stop_target_or_entry_path"))
                if chosen:
                    capacity, _ = self.execute(chosen, bar, info, capacity)
            p = self.portfolio.position
            fills_now = self.fills[fills_before:]
            # Only use full OHLC extremes if the position was held throughout the bar.
            open_entry = any(f.order_id == (p.entry_order if p else -1) and not f.intrabar for f in fills_now)
            exits_now = any(f.side.sign == -(p.direction if p else 0) for f in fills_now)
            if p and (p is p_start or open_entry) and not exits_now:
                p.excursion(bar.high)
                p.excursion(bar.low)
            row = self.portfolio.record(bar.end, bar.close)
            if row["equity"] <= 0:
                raise ValueError("Account equity exhausted")
            if p and row["equity"] < p.contracts * self.risk.config.margin_per_contract:
                raise ValueError("Configured margin breached; broker liquidation is not simulated")
            self.risk.observe(info.trading_date, row["equity"])
            if p and (p is p_start or open_entry) and not exits_now:
                adverse_price = bar.low if p.direction == 1 else bar.high
                self.risk.observe(info.trading_date, self.portfolio.equity(adverse_price))
            values = self.features.update(item.research, reset=bool(item.roll and item.roll.adjustment == "unadjusted_reset"))
            self.feature_rows.append(dict(values, contract=bar.contract))
            self.history.append(item.research)
            context = self.make_context(item, values)
            if self.last_day != info.trading_date:
                self.submit_requests(self.strategy.on_session_start(replace(context, boundary_reason="first_observed_bar")), context)
            self.submit_requests(self.strategy.on_bar(context), context)
            self.context, self.last_day = context, info.trading_date
        if self.context:
            self.submit_requests(self.strategy.on_session_end(replace(self.context, boundary_reason="dataset_end")), self.context)
        for order in self.orders:
            if order.status in ACTIVE:
                order.status = Status.EXPIRED
                order.rejection = "dataset_end"
        return self
