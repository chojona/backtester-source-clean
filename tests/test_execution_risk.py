from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
import pytest
from backtester.instruments import instrument, contract_root
from backtester.execution import (ExecutionCosts, FillConfig, FillModel, OrderRequest, Order,
                                   OrderType, Side, Status, Ambiguity)
from backtester.risk import size_fixed, size_dollar_risk, risk_per_contract, RiskManager, RiskConfig
from backtester.portfolio import Portfolio
from conftest import make_bar


@pytest.mark.parametrize('symbol,tick,value', [('ES',.25,12.5),('MES',.25,1.25),('NQ',.25,5),('MNQ',.25,.5),('GC',.1,10),('MGC',.1,1)])
def test_contract_calculations(symbol,tick,value):
    ins=instrument(symbol)
    assert ins.tick_size == tick
    assert ins.tick_value == value
    assert ins.currency == 'USD'
    assert contract_root(symbol+'Z26') == symbol


def test_decimal_tick_rounding():
    es=instrument('ES')
    assert es.round_tick(100.12,'down') == 100
    assert es.round_tick(100.12,'up') == 100.25
    assert es.round_tick(-.12,'down') == -.25
    assert instrument('GC').round_tick(2010.15) == 2010.2


def order(request, bar=None):
    bar=bar or make_bar()
    return Order(1,bar.timestamp,bar.timestamp.date(),bar.contract,request)


@pytest.mark.parametrize('ticks',[0,1,2,4])
def test_market_fees_slippage_scenarios(ticks):
    bar=make_bar()
    model=FillModel(instrument('ES'),ExecutionCosts(2,1,ticks))
    fill=model.fill(order(OrderRequest(Side.BUY,2)),bar,100)
    assert fill.price == 100 + ticks*.25
    assert fill.fees == 6
    assert fill.slippage == ticks*12.5*2


def test_order_must_wait_for_submission_time():
    bar=make_bar()
    pending=order(OrderRequest(Side.BUY),bar)
    pending.submitted=bar.end
    assert FillModel(instrument('ES')).quote(pending,bar) is None


def test_limit_touch_is_not_default_fill():
    bar=make_bar(low=99)
    pending=order(OrderRequest(Side.BUY,type=OrderType.LIMIT,price=99))
    assert FillModel(instrument('ES')).quote(pending,bar) is None
    model=FillModel(instrument('ES'),config=FillConfig(limit_mode='touch'))
    assert model.quote(pending,bar)[1] == 99
    through=replace(bar,low=98.75)
    assert FillModel(instrument('ES')).quote(pending,through)[1] == 99


def test_limit_fill_never_worse_than_limit():
    model=FillModel(instrument('ES'),ExecutionCosts(slippage_ticks=4))
    bar=make_bar(opening=95,high=100,low=94,close=96)
    fill=model.fill(order(OrderRequest(Side.BUY,type=OrderType.LIMIT,price=99)),bar,1)
    assert fill.price <= 99
    assert fill.slippage == 0


@pytest.mark.parametrize('side,trigger,opening,expected', [(Side.BUY,105,110,110.25),(Side.SELL,95,90,89.75)])
def test_gap_stop_uses_open_not_trigger(side,trigger,opening,expected):
    bar=make_bar(opening=opening)
    pending=order(OrderRequest(side,type=OrderType.STOP,price=trigger))
    fill=FillModel(instrument('ES')).fill(pending,bar,1)
    assert fill.price == expected
    assert not fill.intrabar


def test_partial_fill_and_stop_remainder_becomes_market():
    model=FillModel(instrument('ES'),config=FillConfig(participation=.2))
    first=make_bar(high=106)
    pending=order(OrderRequest(Side.BUY,5,type=OrderType.STOP,price=105))
    fill=model.fill(pending,first,model.capacity(first))
    assert fill.quantity == 2
    assert pending.status == Status.PARTIALLY_FILLED
    assert pending.triggered
    second=make_bar('2026-01-05T09:31',opening=100,volume=20)
    fill=model.fill(pending,second,model.capacity(second))
    assert fill.quantity == 3
    assert fill.price == 100.25
    assert pending.status == Status.FILLED


@pytest.mark.parametrize('policy,expected',[(Ambiguity.CONSERVATIVE,'stop_loss'),(Ambiguity.OPTIMISTIC,'target'),(Ambiguity.STOP_FIRST,'stop_loss'),(Ambiguity.TARGET_FIRST,'target')])
def test_ambiguous_oco(policy,expected):
    bar=make_bar(high=110,low=90)
    stop=order(OrderRequest(Side.SELL,type=OrderType.STOP,price=95,reason='stop_loss'))
    target=order(OrderRequest(Side.SELL,type=OrderType.LIMIT,price=105,reason='target'))
    model=FillModel(instrument('ES'),config=FillConfig(ambiguity=policy))
    chosen, ambiguous=model.choose_bracket(stop,target,bar)
    assert ambiguous
    assert chosen.request.reason == expected


def test_gap_resolves_bracket_ambiguity():
    bar=make_bar(opening=90,high=110,low=89,close=100)
    stop=order(OrderRequest(Side.SELL,type=OrderType.STOP,price=95))
    target=order(OrderRequest(Side.SELL,type=OrderType.LIMIT,price=105))
    chosen,ambiguous=FillModel(instrument('ES')).choose_bracket(stop,target,bar)
    assert chosen is stop
    assert not ambiguous


def test_integer_risk_sizing_includes_roundtrip_costs():
    ins=instrument('NQ')
    costs=ExecutionCosts(2,1,1)
    assert risk_per_contract(20000,19990,ins,costs) == 216
    assert size_dollar_risk(1000,20000,19990,ins,costs,10) == 4
    assert size_dollar_risk(10,20000,19990,ins,costs,10) == 0
    assert size_fixed(20,3) == 3
    with pytest.raises(ValueError):
        OrderRequest(Side.BUY,quantity=1.5)


@pytest.mark.parametrize('entry_side,exit_open', [(Side.BUY, 101), (Side.SELL, 99)])
def test_nq_roundtrip_reference_and_cash_accounting(entry_side, exit_open):
    """One favorable point: $20 gross, $10 slippage, $6 fees, $4 net."""
    ins = instrument('NQ')
    model = FillModel(ins, ExecutionCosts(2, 1, 1))
    entry_bar = replace(make_bar(opening=100), symbol='NQ', contract='NQZ26')
    exit_bar = replace(make_bar('2026-01-05T09:31', opening=exit_open), symbol='NQ', contract='NQZ26')
    entry_req = OrderRequest(entry_side)
    exit_side = Side.SELL if entry_side == Side.BUY else Side.BUY
    entry_fill = model.fill(order(entry_req, entry_bar), entry_bar, 1)
    exit_fill = model.fill(order(OrderRequest(exit_side), exit_bar), exit_bar, 1)
    portfolio = Portfolio(ins, cash=100000)
    info = SimpleNamespace(session='RTH', trading_date=entry_bar.timestamp.date())
    portfolio.open(entry_fill, entry_req, info, risk=100)
    trade = portfolio.close(exit_fill, 'fixture', 'manual')
    assert trade['gross_pnl'] == 20
    assert trade['slippage'] == 10
    assert trade['fees'] == 6
    assert trade['net_pnl'] == 4
    assert portfolio.balance == 100004


def test_daily_loss_lockout_persists_even_after_recovery():
    manager=RiskManager(RiskConfig(max_daily_loss=100))
    day=make_bar().timestamp.date()
    manager.observe(day,10000)
    manager.observe(day,9899)
    assert manager.locked
    manager.observe(day,11000)
    assert manager.locked
    manager.observe(day+timedelta(days=1),11000)
    assert not manager.locked


@pytest.mark.parametrize('change,expected',[
    ({'quantity':11},'max_contracts'), ({'stop_loss':None},'entry_requires_stop'),
    ({'stop_loss':101},'stop_on_wrong_side'), ({'stop_loss':50},'max_risk_per_trade'),
])
def test_entry_risk_rejections(change,expected):
    manager=RiskManager(RiskConfig())
    bar=make_bar()
    manager.observe(bar.timestamp.date(),100000)
    request=replace(OrderRequest(Side.BUY,stop_loss=95),**change)
    reason=manager.entry_rejection(request,100,bar.timestamp,100000,instrument('ES'),ExecutionCosts())
    assert reason.startswith(expected)
