from dataclasses import replace
from datetime import timedelta
import pytest
from backtester.intraday import IntradayEngine
from backtester.execution import Side,OrderRequest,OrderType,ExecutionCosts,FillConfig,Ambiguity,Status
from backtester.risk import RiskConfig
from backtester.strategy import Strategy
from backtester.sessions import SessionCalendar
from backtester.instruments import instrument
from backtester.reports import trade_metrics
from conftest import make_bar,selected


class EnterOnce(Strategy):
    name='test-v1'
    def __init__(self,side=Side.BUY):
        self.side,self.calls=side,[]
    def on_bar(self,context):
        self.calls.append(context)
        if len(self.calls)==1:
            return (OrderRequest(self.side,stop_loss=95 if self.side==Side.BUY else 105,
                                  target=105 if self.side==Side.BUY else 95),)
        return ()


def engine(strategy,**kwargs):
    kwargs.setdefault('risk',RiskConfig(margin_per_contract=1000))
    return IntradayEngine(instrument('ES'),SessionCalendar(),strategy,**kwargs)


def test_next_bar_market_and_conservative_pnl():
    first=make_bar()
    second=make_bar('2026-01-05T09:31',high=106,low=94)
    run=engine(EnterOnce()).run(selected([first,second]))
    trade=run.portfolio.trades[0]
    assert trade['entry_time'] == second.timestamp
    assert trade['entry_price'] == 100.25
    assert trade['exit_price'] == 94.75
    assert trade['gross_pnl'] == -250
    assert trade['fees'] == 6
    assert trade['slippage'] == 25
    assert trade['net_pnl'] == -281
    assert len(run.ambiguous_bars) == 1
    assert run.portfolio.balance == 100000-281
    assert run.portfolio.trade_equity[-1]['equity'] == 100000-281
    assert trade['r_multiple'] == pytest.approx(-281 / trade['initial_risk'])


def test_short_target_pnl():
    run=engine(EnterOnce(Side.SELL)).run(selected([make_bar(),make_bar('2026-01-05T09:31',high=101,low=94)]))
    trade=run.portfolio.trades[0]
    assert trade['direction']=='short'
    assert trade['gross_pnl']==250
    assert trade['net_pnl']==231.5
    assert trade['exit_reason']=='target'


def test_mfe_mae_exclude_unordered_exit_bar_extremes():
    bars=[make_bar(),make_bar('2026-01-05T09:31',high=104,low=99),make_bar('2026-01-05T09:32',high=110,low=99)]
    run=engine(EnterOnce()).run(selected(bars))
    trade=run.portfolio.trades[0]
    assert trade['mfe_points'] == 4.75 # exit fill; does not invent pre-exit move to high 110
    assert trade['mae_points'] == 1.25
    assert trade['holding_seconds'] == 120


def test_immutable_prefix_only_context():
    strategy=EnterOnce()
    run=engine(strategy).run(selected([make_bar(),make_bar('2026-01-05T09:31')]))
    first=strategy.calls[0]
    assert len(first.history)==1
    assert first.history[-1].end==first.timestamp
    assert not hasattr(first,'provider')
    with pytest.raises(TypeError):
        first.account['equity']=0
    with pytest.raises(Exception):
        first.bar.close=999
    assert len(strategy.calls[-1].history)==2


def test_changing_future_bars_does_not_change_earlier_signals_or_features():
    bars=[make_bar(),make_bar('2026-01-05T09:31'),make_bar('2026-01-05T09:32')]
    one=engine(EnterOnce()).run(selected(bars))
    two=engine(EnterOnce()).run(selected(bars[:2]+[replace(bars[2],open=500,high=501,low=499,close=500)]))
    assert one.feature_rows[:2] == two.feature_rows[:2]
    assert one.orders[0].submitted == two.orders[0].submitted
    assert one.fills[0] == two.fills[0]


class EnterWheneverFlat(Strategy):
    def on_bar(self,context):
        if context.position is None:
            return (OrderRequest(Side.BUY,stop_loss=95,target=105),)
        return ()


def test_daily_loss_lockout_blocks_subsequent_entries():
    risk=RiskConfig(max_daily_loss=100,margin_per_contract=1000)
    run=engine(EnterWheneverFlat(),risk=risk).run(selected([
        make_bar(),make_bar('2026-01-05T09:31',high=106,low=94),make_bar('2026-01-05T09:32')]))
    assert len(run.portfolio.trades)==1
    assert any(o.rejection=='daily_loss_lockout' for o in run.orders)


def test_off_tick_orders_rejected():
    class BadPrice(Strategy):
        def on_bar(self,context):
            return (OrderRequest(Side.BUY,stop_loss=95.1),)
    run=engine(BadPrice()).run(selected([make_bar(),make_bar('2026-01-05T09:31')]))
    assert not run.fills
    assert run.orders[0].status == Status.REJECTED


def test_partial_entry_cancels_remainder_explicitly():
    class LargeEntry(Strategy):
        def on_bar(self,context):
            if len(context.history)==1:
                return (OrderRequest(Side.BUY,3,stop_loss=99,target=110),)
    run=engine(LargeEntry(),fills=FillConfig(participation=.1)).run(selected([make_bar(),make_bar('2026-01-05T09:31')]))
    assert run.orders[0].filled_quantity==1
    assert run.orders[0].status == Status.CANCELLED
    assert 'partial_entry_remainder_cancelled' in run.orders[0].rejection


def test_intrabar_entry_cannot_assume_target_before_stop():
    class LimitEntry(Strategy):
        def on_bar(self,context):
            if len(context.history)==1:
                return (OrderRequest(Side.BUY,type=OrderType.LIMIT,price=99,stop_loss=95,target=105),)
    run=engine(LimitEntry()).run(selected([make_bar(),make_bar('2026-01-05T09:31',high=110,low=94)]))
    assert run.portfolio.trades[0]['exit_reason']=='stop_loss'
    assert len(run.ambiguous_bars)==1


def test_drawdown_uses_curve_not_only_final_equity():
    trades=[dict(net_pnl=100,r_multiple=1,gross_pnl=110,fees=5,slippage=5,holding_seconds=60,trading_date='d'),
            dict(net_pnl=-50,r_multiple=-.5,gross_pnl=-40,fees=5,slippage=5,holding_seconds=120,trading_date='d')]
    curve=[dict(drawdown_dollars=50,drawdown_percentage=.005)]
    metrics=trade_metrics(trades,curve,observed_days=2)
    assert metrics['profit_factor']==2
    assert metrics['expectancy']==25
    assert metrics['average_R']==.25
    assert metrics['trades_per_day']==1
    assert metrics['maximum_drawdown_dollars']==50
