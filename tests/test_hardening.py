from dataclasses import replace
from datetime import date
import pytest
from backtester.execution import FillModel,FillConfig,OrderRequest,OrderType,Side,Status
from backtester.instruments import instrument
from backtester.risk import RiskConfig
from backtester.strategy import Strategy,NoOrders
from backtester.features import FeatureEngine
from backtester.sessions import SessionCalendar,local_at
from backtester.rolls import ContinuousSeries
from backtester.research import label_events
from test_intraday import engine,EnterOnce,EnterWheneverFlat
from test_execution_risk import order
from test_rolls_research import config,panel,event_engine,event_bars
from conftest import make_bar,selected,day_bars


def test_engine_rejects_unannounced_contract_switch_and_duplicates():
    for bars in ([make_bar(),make_bar()],
                 [make_bar(),make_bar('2026-01-05T09:31',contract='ESH27')]):
        with pytest.raises(ValueError):
            engine(NoOrders()).run(selected(bars))


def test_partial_target_keeps_residual_protective_stop():
    class Entry(Strategy):
        def on_bar(self,c):
            if len(c.history)==1:
                return (OrderRequest(Side.BUY,3,stop_loss=95,target=105),)
    bars=[make_bar(volume=100),make_bar('2026-01-05T09:31',volume=100),
          make_bar('2026-01-05T09:32',high=106,low=99,volume=10),
          make_bar('2026-01-05T09:33',high=101,low=94,volume=100)]
    run=engine(Entry(),fills=FillConfig(participation=.1)).run(selected(bars))
    assert run.portfolio.position is None
    assert run.portfolio.trades[0]['contracts']==3
    assert run.portfolio.trades[0]['exit_reason']=='stop_loss'
    assert [f.quantity for f in run.fills]==[3,1,2]


def test_intrabar_drawdown_locks_out_even_if_close_recovers():
    class Entry(Strategy):
        def on_bar(self,c):
            if len(c.history)==1:
                return (OrderRequest(Side.BUY,stop_loss=90,target=120),)
    run=engine(Entry(),risk=RiskConfig(max_daily_loss=100,margin_per_contract=1000)).run(selected([
        make_bar(),make_bar('2026-01-05T09:31',high=102,low=97,close=102)]))
    assert run.portfolio.equity_curve[-1]['equity']>100000
    assert run.risk.locked


def test_day_orders_expire_at_next_trading_date():
    class Pending(Strategy):
        def on_bar(self,c):
            if len(c.history)==1:
                return (OrderRequest(Side.BUY,type=OrderType.LIMIT,price=90,stop_loss=85),)
    run=engine(Pending()).run(selected([make_bar(),make_bar('2026-01-05T18:00')]))
    assert run.orders[0].status==Status.EXPIRED


def test_margin_entry_rejection():
    run=engine(EnterOnce(),risk=RiskConfig(margin_per_contract=100001)).run(selected([make_bar(),make_bar('2026-01-05T09:31')]))
    assert run.orders[0].rejection=='insufficient_margin'


def test_maximum_trades_and_entry_cutoff():
    run=engine(EnterWheneverFlat(),risk=RiskConfig(max_trades_per_day=1,margin_per_contract=1000)).run(selected([
        make_bar(),make_bar('2026-01-05T09:31',high=106,low=94),make_bar('2026-01-05T09:32')]))
    assert any(o.rejection=='max_trades_per_day' for o in run.orders)
    run=engine(EnterOnce()).run(selected([make_bar('2026-01-05T15:54'),make_bar('2026-01-05T15:55')]))
    assert run.orders[0].rejection=='outside_entry_window'


def test_zero_volume_and_unfilled_triggered_stop():
    model=FillModel(instrument('ES'))
    zero=make_bar(high=106,volume=0)
    assert model.capacity(zero)==0
    stop=order(OrderRequest(Side.BUY,type=OrderType.STOP,price=105))
    assert model.fill(stop,zero,0) is None
    assert stop.triggered
    assert model.fill(stop,make_bar('2026-01-05T09:31',opening=100),1).price==100.25


def test_skipped_day_does_not_mislabel_old_levels_as_yesterday():
    stream=FeatureEngine(SessionCalendar())
    for bar in day_bars():
        stream.update(bar)
    values=stream.update(make_bar('2026-01-06T18:00'))
    assert values['PDH'] is None
    assert not values['previous_day_complete']


def test_tomorrows_data_cannot_change_todays_features():
    earlier=day_bars(minutes=5)
    future=day_bars(date(2026,1,6),minutes=5)
    def calculate(changed):
        stream=FeatureEngine(SessionCalendar())
        snapshots=[dict(stream.update(b)) for b in earlier]
        for b in future:
            stream.update(replace(b,open=900,high=901,low=899,close=900,volume=999999) if changed else b)
        return snapshots
    assert calculate(False)==calculate(True)


def test_partial_prior_session_cannot_trigger_volume_roll():
    with pytest.raises(ValueError,match='complete prior-session'):
        list(ContinuousSeries(SessionCalendar(),config(policy='volume')).select(panel()))


def test_open_interest_roll_requires_published_snapshot():
    bars=[]
    for day in (date(2026,1,5),date(2026,1,6)):
        for b in day_bars(day,minutes=5):
            bars += [b,replace(b,contract='ESH27',open=200,high=201,low=199,close=200)]
    with pytest.raises(ValueError,match='point-in-time OI'):
        list(ContinuousSeries(SessionCalendar(),config(policy='open_interest')).select(bars))


def test_closed_market_horizon_is_censored():
    strategy,_=event_engine()
    event=dict(strategy.events[0],timestamp=local_at(date(2026,1,5),'16:14'))
    bars=[make_bar('2026-01-05T16:14'),make_bar('2026-01-05T16:30')]
    results=label_events([event],selected(bars),SessionCalendar(),strategy.config)
    assert not results[0]['forward']['5']['complete']


def test_short_approach_excursion_signs():
    strategy,_=event_engine()
    event=dict(strategy.events[0],away_direction=-1,direction_of_approach='from_below')
    results=label_events([event],selected(event_bars()),SessionCalendar(),strategy.config)
    assert results[0]['forward']['5']['mfe_points']==3
    assert results[0]['forward']['5']['mae_points']==9


def test_optimistic_entry_still_requires_target_trade_through():
    class Entry(Strategy):
        def on_bar(self,c):
            if len(c.history)==1:
                return (OrderRequest(Side.BUY,type=OrderType.LIMIT,price=99,stop_loss=95,target=105),)
    run=engine(Entry(),fills=FillConfig(ambiguity='OPTIMISTIC')).run(selected([
        make_bar(),make_bar('2026-01-05T09:31',high=105,low=94)]))
    assert run.portfolio.trades[0]['exit_reason']=='stop_loss'


def test_individual_contract_expiration_applies_when_supplied():
    from backtester.rolls import RollConfig
    with pytest.raises(ValueError,match='past declared expiration'):
        list(ContinuousSeries(SessionCalendar(),RollConfig(expirations={'ESZ26':'2026-01-04'})).select([make_bar()]))


@pytest.mark.parametrize('symbol',['ES','MES','NQ','MNQ','GC','MGC'])
def test_all_instruments_execute_with_centralized_point_and_tick_values(symbol):
    from backtester.intraday import IntradayEngine
    ins=instrument(symbol)
    bars=[replace(b,symbol=symbol,contract=symbol+'Z26') for b in [make_bar(),make_bar('2026-01-05T09:31',high=106,low=94)]]
    run=IntradayEngine(ins,SessionCalendar(ins.session_template),EnterOnce(),
                      risk=RiskConfig(margin_per_contract=1000)).run(selected(bars))
    trade=run.portfolio.trades[0]
    assert trade['gross_pnl']==-5*ins.point_value
    assert trade['slippage']==pytest.approx(2*ins.tick_value)
    assert trade['net_pnl']==pytest.approx(-5*ins.point_value-2*ins.tick_value-6)


def test_engine_reuse_and_nonchronological_feature_updates_fail():
    run=engine(NoOrders()).run(selected([make_bar()]))
    with pytest.raises(ValueError,match='single-run'):
        run.run(selected([make_bar()]))
    stream=FeatureEngine(SessionCalendar())
    stream.update(make_bar())
    with pytest.raises(ValueError,match='chronological'):
        stream.update(make_bar())
