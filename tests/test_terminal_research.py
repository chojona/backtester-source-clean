"""v0.3 tests only constructed inputs. No historical or holdout files opened."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from backtester.features import VWAP
from backtester.research_nq.adapter import ReadOnlyExploratoryAdapter
from backtester.research_nq.testing_support import bound_manifest, traded
from backtester.terminal.research import SPEC, detect, eligible_sessions, label, parse, replay_view, run
from backtester.terminal.server import Store, Workspace, demo_inputs

CONFIG = dict(strategy=SPEC['id'], contract='NQZ26', start='2026-01-05',
              end='2026-01-19', eligibility='complete_observed')


@pytest.fixture(scope='module')
def inputs():
    return demo_inputs()


@pytest.fixture(scope='module')
def result(inputs):
    adapter, partitions = inputs
    return run(adapter, partitions, CONFIG, {'classification': 'SYNTHETIC'})


def test_vwap_known_weighted_example_and_session_reset(inputs):
    t = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
    a, b = traded(t, 100), replace(traded(t+timedelta(minutes=1), 110), volume=30)
    v = VWAP('typical')
    assert v.update(a) == 100
    assert v.update(b) == 107.5
    adapter, partitions = inputs
    groups, _ = eligible_sessions(adapter, partitions, CONFIG['start'], CONFIG['end'])
    for bars in groups.values():
        values, _ = detect(bars)
        assert values[0] == pytest.approx((bars[0].high+bars[0].low+bars[0].close)/3)


def test_signal_causality_prefix_invariance_and_mutated_future(inputs):
    adapter, partitions = inputs
    groups, _ = eligible_sessions(adapter, partitions, CONFIG['start'], CONFIG['end'])
    bars = next(iter(groups.values()))
    _, events = detect(bars)
    assert events
    for event in events:
        i = event['bar_index']
        assert parse(event['signal_at']) == bars[i].end
        assert '09:45' <= bars[i].end.astimezone(__import__('backtester.sessions', fromlist=['NY']).NY).strftime('%H:%M') <= '12:00'
        assert detect(bars[:i+1])[1] == [e for e in events if e['bar_index'] <= i]
        changed = bars[:i+1] + [replace(b, close=b.close+500, high=b.high+501) for b in bars[i+1:]]
        assert [e for e in detect(changed)[1] if e['bar_index'] <= i] == detect(bars[:i+1])[1]


def test_acceptance_and_rejection_objective_conditions():
    t = datetime(2026, 1, 5, 14, 42, tzinfo=timezone.utc)  # 09:42 ET
    bars = [traded(t+timedelta(minutes=i), p) for i,p in enumerate([100,99,102,103])]
    events = detect(bars)[1]
    assert events[-1]['classification'] == 'acceptance'
    assert events[-1]['direction'] == 1
    bars = [traded(t-timedelta(minutes=2)+timedelta(minutes=i), p) for i,p in enumerate([100,102,103,103,103])]
    bars[-1] = replace(bars[-1], low=99)
    events = detect(bars)[1]
    assert events[-1]['classification'] == 'rejection'


def rebound(adapter, bars):
    manifest, data, calendar = bound_manifest(bars, time_range=dict(adapter.manifest.time_range))
    return ReadOnlyExploratoryAdapter(manifest, bars, dataset_bytes=data, calendar_bytes=calendar)


@pytest.mark.parametrize('change', ['missing', 'unresolved', 'materialized', 'late', 'duplicate'])
def test_eligibility_rejects_bad_session(inputs, change):
    adapter, partitions = inputs
    bars = [bar for bar,_ in adapter.classify_all()]
    i = 20
    if change == 'missing':
        del bars[i]
    elif change == 'unresolved':
        bars[i] = replace(bars[i], coverage_state='UNKNOWN')
    elif change == 'materialized':
        bars[i] = replace(bars[i], bar_state='NO_TRADE', open=bars[i].close, high=bars[i].close, low=bars[i].close, volume=0, published=False, coverage_evidence=__import__('backtester.research_nq.classifications',fromlist=['MATERIALIZATION_TOKEN']).MATERIALIZATION_TOKEN)
    elif change == 'late':
        bars[i] = replace(bars[i], source_ts_event_ns=int((bars[i].end+timedelta(seconds=1)).timestamp()*1e9))
    elif change == 'duplicate':
        bars.insert(i,bars[i])
    with pytest.raises(ValueError, match='No eligible'):
        eligible_sessions(rebound(adapter,bars),partitions,'2026-01-05','2026-01-05')


def test_holdout_and_parameter_search_blocked(inputs):
    adapter, partitions=inputs
    holdout=next(d for d,p in partitions.items() if p=='final_holdout')
    with pytest.raises(ValueError,match='holdout'):
        run(adapter,partitions,dict(CONFIG,start=holdout,end=holdout),{})
    with pytest.raises(ValueError,match='Only fixed'):
        run(adapter,partitions,dict(CONFIG,threshold=.1),{})
    with pytest.raises(ValueError,match='contract'):
        run(adapter,partitions,dict(CONFIG,contract='NQH27'),{})
    changed=dict(partitions);changed['2026-01-05']='validation'
    with pytest.raises(ValueError,match='chronological'):
        run(adapter,changed,CONFIG,{})


def test_replay_hides_future_and_all_labels(result):
    event=result['events'][0]
    before=parse(event['signal_at'])-timedelta(microseconds=1)
    view=replay_view(result,before.isoformat())
    assert all(parse(e['signal_at'])<=before for e in view['events'])
    assert all(parse(b['available_at'])<=before for b in view['candles'])
    keys=set(view) | {key for event in view['events'] for key in event}
    for forbidden in ['outcomes','baseline','event_count','session_count','metrics','provenance','hypothetical_net_usd_per_event','coverage','partitions']:
        assert forbidden not in keys
    exact=replay_view(result,event['signal_at'])
    assert exact['events'][-1]['signal_at']==event['signal_at']
    assert set(exact['events'][-1]) == {'bar_time','signal_at','contract','direction','classification','vwap','reference_close','session'}


def test_alignment_costs_and_forward_windows(result):
    bars={b['time']:b for b in result['candles']}
    assert result['event_count'] > 0
    for e in result['events']:
        b=bars[e['bar_time']]
        assert b['contract']==e['contract']==result['contract']
        assert b['session']==e['session']
        assert b['available_at']==e['signal_at']
        assert b['vwap']==e['vwap']
        for h in (5,10,15):
            outcome=e['outcomes'][str(h)]
            assert parse(outcome['outcome_at'])==parse(e['signal_at'])+timedelta(minutes=h)
            assert outcome['mfe_points']>=0 and outcome['mae_points']<=0
        scenario=e['outcomes']['cost_scenario']
        assert parse(scenario['entry_at'])>parse(e['signal_at'])
        assert parse(scenario['exit_at'])-parse(scenario['entry_at'])==timedelta(minutes=15)
        assert scenario['cost_usd']==15
        assert scenario['net_usd']==pytest.approx(scenario['gross_usd']-15)
    assert result['strategy_metrics']['sharpe'] is None
    assert result['strategy_metrics']['equity_curve'] is None
    assert any(m['return_ci'] is not None for m in result['metrics'])


def test_matched_baseline_is_same_partition_time_other_session(result):
    e=result['events'][0]
    target=parse(e['signal_at']).time()
    from backtester.sessions import NY
    target=parse(e['signal_at']).astimezone(NY).time()
    values=[]
    byday={}
    for b in result['candles']:
        byday.setdefault(b['session'],[]).append(b)
    for day,bars in byday.items():
        if day==e['session'] or result['partitions'][day]!=e['partition']:continue
        i=next(i for i,b in enumerate(bars) if parse(b['available_at']).astimezone(NY).time()==target)
        values.append(e['direction']*(bars[i+5]['close']/bars[i]['close']-1))
    assert e['baseline_sessions']==len(values)
    assert e['baseline']['5']==pytest.approx(sum(values)/len(values))


def test_reproducible_and_immutable(inputs,result,tmp_path):
    adapter,partitions=inputs
    rerun=run(adapter,partitions,CONFIG,{'classification':'SYNTHETIC'})
    assert rerun==result
    store=Store(tmp_path)
    identity=store.put(result)
    before=(tmp_path/(identity+'.json')).read_bytes()
    assert store.put(rerun)==identity
    assert (tmp_path/(identity+'.json')).read_bytes()==before
    assert store.get(identity)==result
    damaged=json.loads(before);damaged['event_count']+=1
    (tmp_path/(identity+'.json')).write_text(json.dumps(damaged))
    with pytest.raises(ValueError,match='integrity'):
        store.get(identity)
