from dataclasses import replace,asdict
from datetime import date,timedelta
import pytest
from backtester.rolls import ContinuousSeries,RollConfig,SelectedBar,retrospective_back_adjust
from backtester.sessions import SessionCalendar,local_at
from backtester.research import WeeklyVWAPReaction,ReactionConfig,label_events,research_statistics
from backtester.strategy import Strategy
from backtester.execution import OrderRequest,Side,ExecutionCosts
from backtester.intraday import IntradayEngine
from backtester.risk import RiskConfig
from backtester.instruments import instrument
from conftest import make_bar,day_bars,selected


def panel():
    return [make_bar('2026-01-05T09:30',contract='ESZ26',opening=100,volume=100),
            make_bar('2026-01-05T09:30',contract='ESH27',opening=200,volume=200),
            make_bar('2026-01-06T09:30',contract='ESZ26',opening=101,volume=100),
            make_bar('2026-01-06T09:30',contract='ESH27',opening=201,volume=200),
            make_bar('2026-01-06T09:31',contract='ESZ26',opening=102,volume=100),
            make_bar('2026-01-06T09:31',contract='ESH27',opening=202,volume=200)]


def config(**kwargs):
    options=dict(expirations={'ESZ26':'2026-01-07','ESH27':'2026-04-01'},days_before_expiration=1)
    options.update(kwargs)
    return RollConfig(**options)


def test_fixed_roll_uses_paired_opens_and_causal_adjustment():
    series=ContinuousSeries(SessionCalendar(),config())
    rows=list(series.select(panel()))
    assert [r.raw.contract for r in rows]==['ESZ26','ESH27','ESH27']
    assert rows[1].raw.open==201
    assert rows[1].research.open==101
    assert rows[2].research.open==102
    assert series.records[0].price_difference==100
    assert series.records[0].old_contract=='ESZ26'


def test_roll_ratio_and_unadjusted_are_explicit():
    ratio=list(ContinuousSeries(SessionCalendar(),config(adjustment='forward_ratio')).select(panel()))
    assert ratio[1].research.open==pytest.approx(101)
    unadjusted=list(ContinuousSeries(SessionCalendar(),config(adjustment='unadjusted_reset')).select(panel()))
    assert unadjusted[1].research.open==201
    with pytest.raises(ValueError):
        config(adjustment='back_adjusted')


@pytest.mark.parametrize('policy',['volume','open_interest'])
def test_liquidity_roll_uses_prior_session_not_current_bar(policy,tmp_path):
    bars=[]
    for day in (date(2026,1,5),date(2026,1,6)):
        for bar in day_bars(day,minutes=5):
            bars.extend([replace(bar,volume=100,open_interest=100,
                                         open_interest_available_at=bar.timestamp,
                                         open_interest_state='CAUSAL_CAPTURE_BOUND'),
                         replace(bar,contract='ESH27',open=200,high=201,low=199,close=200,volume=200,open_interest=200,
                                        open_interest_available_at=bar.timestamp,
                                        open_interest_state='CAUSAL_CAPTURE_BOUND')])
    registry=None
    if policy=='open_interest':
        from capture_helpers import capture_test_registry, verify_bars
        bars=verify_bars(bars,tmp_path/'capture')
        registry=capture_test_registry(tmp_path/'capture')
    rows=list(ContinuousSeries(SessionCalendar(),config(policy=policy),_test_registry=registry).select(bars))
    assert rows[0].raw.contract=='ESZ26'
    first_tuesday=next(r for r in rows if SessionCalendar().classify(r.raw.timestamp).trading_date==date(2026,1,6))
    assert first_tuesday.raw.contract=='ESH27'
    changed_bars=[replace(b,volume=100000 if b.contract=='ESZ26' else 1,
                            open_interest=100000 if b.contract=='ESZ26' else 1,
                            open_interest_verification=None)
             if SessionCalendar().classify(b.timestamp).trading_date==date(2026,1,6) else b for b in bars]
    other_registry=registry
    if policy=='open_interest':
        from capture_helpers import capture_test_registry as _reg, verify_bars as _verify
        from backtester.evidence_registry import EvidenceRegistry
        # Re-derive changed day-2 bars from new artifacts; day-1 verified bars stay.
        day2=[b for b in changed_bars if SessionCalendar().classify(b.timestamp).trading_date==date(2026,1,6)]
        verified_day2=iter(_verify(day2,tmp_path/'capture2'))
        changed=[next(verified_day2) if SessionCalendar().classify(b.timestamp).trading_date==date(2026,1,6) else b for b in changed_bars]
        other_registry=EvidenceRegistry.for_testing(capture_manifest_sha256s=[
            c.manifest_sha256 for c in registry.capture_manifests] + [
            c.manifest_sha256 for c in _reg(tmp_path/'capture2').capture_manifests])
    else:
        changed=changed_bars
    other=list(ContinuousSeries(SessionCalendar(),config(policy=policy),_test_registry=other_registry).select(changed))
    assert [r.raw.contract for r in rows]==[r.raw.contract for r in other]


def test_roll_missing_old_quote_or_expiration_fails():
    with pytest.raises(ValueError,match='expiration'):
        list(ContinuousSeries(SessionCalendar(),RollConfig()).select(panel()))
    with pytest.raises(ValueError,match='synchronous'):
        list(ContinuousSeries(SessionCalendar(),config()).select([b for i,b in enumerate(panel()) if i!=2]))


def test_offline_back_adjustment_is_separate():
    rows=list(ContinuousSeries(SessionCalendar(),config()).select(panel()))
    adjusted=retrospective_back_adjust(rows)
    assert adjusted[0].open==200
    assert rows[0].research.open==100
    ratio=retrospective_back_adjust(rows,'ratio')
    assert ratio[0].open==pytest.approx(100*201/101)


def test_roll_reopen_does_not_book_contract_gap():
    class Entry(Strategy):
        def on_bar(self,c):
            if len(c.history)==1:
                return (OrderRequest(Side.BUY,stop_loss=90,target=150),)
    bars=[make_bar('2026-01-05T09:30'),make_bar('2026-01-05T09:31')]
    bars += [make_bar('2026-01-06T09:30',opening=100),make_bar('2026-01-06T09:30',opening=200,contract='ESH27')]
    rows=list(ContinuousSeries(SessionCalendar(),config()).select(bars))
    run=IntradayEngine(instrument('ES'),SessionCalendar(),Entry(),costs=ExecutionCosts(0,0,0),
        risk=RiskConfig(margin_per_contract=1000),roll_position_policy='reopen').run(rows)
    assert run.portfolio.balance==100000
    assert run.portfolio.equity(200)==100000
    assert run.portfolio.position.contract=='ESH27'
    assert run.portfolio.position.stop==190
    assert run.portfolio.trades[0]['exit_reason']=='contract_roll'


def event_bars():
    bars=[make_bar('2026-01-05T09:30',opening=100,close=100),
          make_bar('2026-01-05T09:31',opening=102,high=103,low=101,close=102),
          make_bar('2026-01-05T09:32',opening=103,high=104,low=99,close=103)]
    start=bars[-1].end
    bars += [make_bar(start+timedelta(minutes=i),opening=103,high=110,low=98,close=103) for i in range(60)]
    return bars


def event_engine(bars=None,config=None):
    config=config or ReactionConfig(require_complete_week=False)
    strategy=WeeklyVWAPReaction(config)
    run=IntradayEngine(instrument('ES'),SessionCalendar(),strategy,feature_config={'basis':'close'}).run(selected(bars or event_bars()))
    return strategy,run


def test_event_definition_uses_lagged_vwap_and_first_touch_only():
    strategy,run=event_engine()
    assert len(strategy.events)==1
    event=strategy.events[0]
    assert event['reference_level']==101
    assert event['timestamp']==event_bars()[2].end
    assert event['direction_of_approach']=='from_above'
    assert event['distance_traveled_before_touch_points']==1
    assert not run.orders
    assert not run.portfolio.trades


def test_default_rejects_partial_week_warmup():
    strategy,run=event_engine(config=ReactionConfig())
    assert not strategy.events


def test_future_changes_cannot_change_event_discovery_prefix():
    bars=event_bars()
    one,_=event_engine(bars)
    changed=bars[:3]+[replace(b,open=500,high=501,low=499,close=500,volume=1000000) for b in bars[3:]]
    two,_=event_engine(changed)
    assert one.events[0]==two.events[0]


def test_forward_mfe_mae_math_and_ambiguous_thresholds():
    strategy,_=event_engine()
    results=label_events(strategy.events,selected(event_bars()),SessionCalendar(),strategy.config)
    for h in ('5','15','30','60'):
        assert results[0]['forward'][h]['complete']
        assert results[0]['forward'][h]['mfe_points']==9
        assert results[0]['forward'][h]['mae_points']==3
    # Default through=5 was not crossed; threshold 5 succeeds.
    assert results[0]['threshold_outcomes']['5']['away_before_through'] is True
    assert results[0]['threshold_outcomes']['10']['no_passage_within_horizon']
    stats=research_statistics(results,strategy.config)
    assert stats['horizon_distributions']['5']['MFE']['mean']==9
    assert stats['threshold_results']['5']['success_rate_resolved']==1


def test_ambiguous_research_bar_is_flagged_with_policy():
    config=ReactionConfig(require_complete_week=False,through_points=2)
    strategy,_=event_engine(config=config)
    conservative=label_events(strategy.events,selected(event_bars()),SessionCalendar(),config)
    optimistic=label_events(strategy.events,selected(event_bars()),SessionCalendar(),config,'OPTIMISTIC')
    assert conservative[0]['threshold_outcomes']['5']['away_before_through'] is False
    assert optimistic[0]['threshold_outcomes']['5']['away_before_through'] is True
    assert conservative[0]['threshold_outcomes']['5']['ambiguous_bars']==1


def test_dataset_end_and_missing_bars_censor_outcomes():
    strategy,_=event_engine()
    results=label_events(strategy.events,selected(event_bars()[:5]),SessionCalendar(),strategy.config)
    assert not results[0]['forward']['5']['complete']
    assert results[0]['forward']['5']['mfe_points'] is None
    missing=event_bars()
    del missing[4]
    results=label_events(strategy.events,selected(missing),SessionCalendar(),strategy.config)
    assert results[0]['forward']['5']['censored_reason']=='missing_interval_or_market_closure'


def test_future_labels_do_not_mutate_strategy_events():
    strategy,_=event_engine()
    before=[dict(e) for e in strategy.events]
    label_events(strategy.events,selected(event_bars()),SessionCalendar(),strategy.config)
    assert strategy.events==before
    assert 'forward' not in strategy.events[0]


def test_roll_censors_forward_event():
    strategy,_=event_engine()
    rows=selected(event_bars())
    rows[4]=replace(rows[4],raw=replace(rows[4].raw,contract='ESH27'))
    result=label_events(strategy.events,rows,SessionCalendar(),strategy.config)
    assert result[0]['forward']['5']['censored_reason']=='contract_roll'


def test_session_vwap_research_uses_same_event_interface():
    strategy,_=event_engine(config=ReactionConfig(level='session_vwap',require_complete_week=False))
    assert strategy.events[0]['level']=='session_vwap'
