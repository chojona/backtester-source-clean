"""Independent arithmetic and adversarial prefix tests; no empirical claims."""
from dataclasses import replace, FrozenInstanceError
from datetime import date, timedelta
import json
import math
import subprocess
import sys

import pytest

from backtester.sessions import SessionCalendar, local_at
from backtester.rolls import SelectedBar, ContinuousSeries, RollConfig
from backtester.volatility import (
    log_return, realized_variance, semivariances, bipower_variation,
    threshold_bipower_variation, jump_variation, realized_quarticity,
    realized_range, RealizedVolatility,
)
from conftest import make_bar, day_bars


@pytest.mark.parametrize('r', [[0, 0, 0], [.01, .02, .03], [-.01, -.02, -.03], [.01, -.02, .03], [0, .2, 0]])
def test_scalar_arithmetic(r):
    squares = [x*x for x in r]
    assert realized_variance(r) == pytest.approx(sum(squares))
    positive, negative = semivariances(r)
    assert positive == pytest.approx(sum(x*x for x in r if x > 0))
    assert negative == pytest.approx(sum(x*x for x in r if x < 0))
    assert positive + negative == pytest.approx(realized_variance(r))
    assert bipower_variation(r) == pytest.approx(math.pi/2 * (abs(r[0]*r[1]) + abs(r[1]*r[2])))
    assert realized_quarticity(r) == pytest.approx(sum(x**4 for x in r))  # n/3=1
    assert jump_variation(realized_variance(r), bipower_variation(r)) >= 0


def test_known_jump_and_clipping():
    assert bipower_variation([0, .2, 0]) == 0
    assert jump_variation(.04, 0) == .04
    assert jump_variation(.01, .02) == 0
    assert jump_variation(None, 0) is None


def test_tbpv_thresholds_and_equality():
    r = [.01, .2, -.01, .01]
    assert threshold_bipower_variation(r, [.0001]*4) == pytest.approx(math.pi/2 * .0001)
    assert threshold_bipower_variation(r, [1]*4) == bipower_variation(r)
    assert threshold_bipower_variation([.2, .2], [.001]*2) == 0


@pytest.mark.parametrize('values', [[float('nan')], [float('inf')], [None]])
@pytest.mark.parametrize('function', [realized_variance, semivariances, bipower_variation, realized_quarticity])
def test_bad_returns_never_silently_drop(function, values):
    with pytest.raises((ValueError, TypeError)):
        function(values)


@pytest.mark.parametrize('theta', [[], [0, 1], [-1, 1], [float('nan'), 1]])
def test_bad_thresholds(theta):
    with pytest.raises(ValueError):
        threshold_bipower_variation([.01, .01], theta)


@pytest.mark.parametrize('prices', [(0, 1), (-1, 1), (float('nan'), 1), (1, float('inf'))])
def test_log_price_domain(prices):
    with pytest.raises(ValueError):
        log_return(*prices)


def test_numerics_and_empty_windows():
    assert log_return(1e300, 1e-300) == pytest.approx(-600 * math.log(10))
    assert log_return(1.0, 1.0 + 2**-52) == pytest.approx(2**-52, rel=1e-15)
    assert realized_variance([]) is None
    assert semivariances([]) == (None, None)
    assert bipower_variation([.01]) is None
    assert realized_quarticity([]) is None
    assert realized_range([]) is None
    assert realized_variance([1e-150]*3) == pytest.approx(3e-300, abs=0)


def test_range_exact_normalization():
    bar = make_bar(opening=2, low=1, high=math.e, close=2)
    assert realized_range([bar]*3) == pytest.approx(3 / (4*math.log(2)))


def path(returns, start=None, contract='ESZ26'):
    start = start or local_at(date(2026, 1, 4), '18:00')
    price = 100.
    bars = []
    for i, r in enumerate(returns):
        close = price * math.exp(r)
        bars.append(make_bar(start + i*timedelta(minutes=1), opening=price, close=close,
                             high=max(price, close), low=min(price, close), contract=contract))
        price = close
    return bars


def run(bars, calendar=None, **kwargs):
    stream = RealizedVolatility(calendar or SessionCalendar(), **kwargs)
    return [stream.update(b, as_of=b.end) for b in bars]


@pytest.mark.parametrize('r', [0, .001, -.001])
def test_stream_constant_returns_and_coarse_sampling(r):
    rows = run(path([r]*31))
    end = rows[-1]
    assert end.prefix_complete and not end.session_complete
    assert end.rv_1m == pytest.approx(31*r*r)
    assert end.rv_5m == pytest.approx(6*(5*r)**2)
    assert end.rv_15m == pytest.approx(2*(15*r)**2)
    assert end.samples_5m == 6 and end.covered_minutes_15m == 30
    assert end.bpv == pytest.approx(math.pi/2 * 30*r*r)
    assert end.quarticity == pytest.approx(31/3 * 31*r**4)
    assert end.realized_range == pytest.approx(31*r*r/(4*math.log(2)))
    assert end.rv_intraday_to_now == end.rv_1m
    assert rows[3].rv_5m is None
    assert rows[13].rv_15m is None


def test_alternation_coarse_uses_net_log_return():
    row = run(path([.01, -.01]*15))[-1]
    assert row.rv_1m == pytest.approx(.003)
    assert row.rv_5m == pytest.approx(6 * .0001)
    assert row.rv_15m == pytest.approx(2 * .0001)


def test_tbpv_stream_explicit_configuration():
    bars = path([.01, .2, .01, .01])
    assert run(bars)[-1].tbpv is None
    row = run(bars, tbpv_squared_threshold=.00011)[-1]
    assert row.tbpv == pytest.approx(math.pi/2 * .0001)
    assert row.tbpv_squared_threshold == .00011


def test_missing_bar_nulls_not_zero_or_bridged():
    bars = path([.01]*10)
    rows = run(bars[:2] + bars[3:])
    assert rows[-1].missing_bars_to_now == 1
    assert rows[-1].rv_1m is None and rows[-1].rv_5m is None
    assert rows[-1].observed_rv == pytest.approx(9*.0001)
    assert rows[-1].samples_5m == 1  # only second five-minute block intact


def test_partial_first_session():
    row = run(path([.01]*5, local_at(date(2026, 1, 5), '09:30')))[-1]
    assert not row.prefix_complete
    assert row.rv_1m is None
    assert row.rv_rth == pytest.approx(5*.0001)
    assert row.rv_overnight is None
    assert row.segment_prefix_complete


@pytest.mark.parametrize('change', [dict(timestamp=local_at(date(2026,1,4),'18:00:30')),
                                    dict(duration=timedelta(minutes=5)), dict(open=-1,low=-1)])
def test_bad_stream_bar_rejected_without_mutation(change):
    bar = path([.01])[0]
    stream = RealizedVolatility(SessionCalendar())
    with pytest.raises(ValueError):
        stream.update(replace(bar, **change), as_of=bar.end + timedelta(minutes=5))
    assert stream.update(bar, as_of=bar.end).observed_bars == 1


def test_duplicates_ordering_future_and_immutability():
    bars = path([.01]*3)
    stream = RealizedVolatility(SessionCalendar())
    with pytest.raises(ValueError, match='complete'):
        stream.update(bars[0], as_of=bars[0].timestamp)
    first = stream.update(bars[0], as_of=bars[0].end)
    for bar in (bars[0], replace(bars[0], timestamp=bars[0].timestamp-timedelta(minutes=1))):
        with pytest.raises(ValueError):
            stream.update(bar, as_of=bars[-1].end)
    with pytest.raises(ValueError):
        stream.update(SelectedBar(bars[1], bars[1]), as_of=bars[1].end)
    with pytest.raises(FrozenInstanceError):
        first.rv_1m = 999
    assert stream.update(bars[1], as_of=bars[1].end).observed_bars == 2


def test_future_perturbation_and_truncation():
    bars = path([.001]*45)
    original = run(bars)
    altered = bars[:20] + path([.2]*25, bars[20].timestamp)
    assert run(altered)[:20] == original[:20]
    for n in (1, 5, 15, 20, 44):
        assert run(bars[:n]) == original[:n]


def test_session_segments_and_no_close_gap_across_days():
    calendar = SessionCalendar()
    bars = day_bars(calendar=calendar)
    # Move the RTH opening minute only: both its up and following down return belong to RTH.
    i = next(i for i,b in enumerate(bars) if calendar.classify(b.timestamp).session == 'RTH')
    bars[i] = replace(bars[i], high=101, close=101)
    rows = run(bars, calendar)
    end = rows[-1]
    a = math.log(101/100)
    assert end.rv_rth == pytest.approx(2*a*a)
    assert end.rv_overnight == 0 and end.rv_post_rth == 0
    assert end.rv_1m == pytest.approx(end.rv_rth + end.rv_overnight + end.rv_post_rth)
    assert end.session_complete
    next_day = path([0], local_at(date(2026,1,5),'18:00'))
    next_day[0] = replace(next_day[0], open=1000, high=1000, low=1000, close=1000)
    assert run(bars + next_day)[-1].rv_1m == 0


def test_halt_excludes_return_and_bpv_pair():
    calendar = SessionCalendar(overrides={'2026-01-05': {'breaks': [('09:32','09:34')]}})
    bars = path([.01]*5, local_at(date(2026,1,5),'09:30'))
    rows = run(bars[:2] + bars[4:], calendar)
    assert rows[-1].rv_rth == pytest.approx(3*.0001)
    assert rows[-1].missing_bars_to_now == 930  # missing overnight prefix only
    assert rows[-1].segment_prefix_complete


def test_roll_has_no_cross_contract_return():
    first = path([0]*5)
    second = path([0]*5, first[-1].end, contract='ESH27')
    second = [replace(b, open=1000, high=1000, low=1000, close=1000) for b in second]
    rows = run(first + second)
    assert rows[5].contract == 'ESH27' and rows[5].observed_rv == 0
    assert rows[-1].rv_1m is None and rows[-1].missing_bars_to_now == 5
    assert rows[-1].observed_bars == 5


def test_roll_adapter_raw_vs_adjusted_prices():
    bars = path([.01]*5)
    selected = [SelectedBar(b, replace(b, open=b.open+100, high=b.high+100,
                                     low=b.low+100, close=b.close+100)) for b in bars]
    assert run([b.raw for b in selected])[-1].rv_1m == pytest.approx(.0005)


def test_unknown_coverage_not_flattened():
    bars = path([.01]*3)
    bars[1] = replace(bars[1], coverage_state='UNKNOWN')
    row = run(bars)[-1]
    assert row.rv_1m is None and row.unknown_bars == 1
    assert row.observed_rv == pytest.approx(.0002)


def test_explicit_no_trade_counted_with_provenance():
    bar = path([0])[0]
    bar = replace(bar, volume=0, bar_state='NO_TRADE', coverage_state='PROVIDER_AVAILABLE', published=False)
    row = run([bar])[0]
    assert row.rv_1m == 0 and row.no_trade_bars == 1


@pytest.mark.parametrize('template,clock', [('equity','09:30'), ('gold','08:20')])
def test_product_calendar_and_segment_anchor(template, clock):
    calendar = SessionCalendar(template)
    bars = path([.01]*15, local_at(date(2026,1,5),clock))
    if template == 'gold':
        bars = [replace(b, symbol='GC',contract='GCJ26') for b in bars]
    row = run(bars, calendar)[-1]
    assert row.rv_rth == pytest.approx(.0015)
    assert row.samples_15m == 1  # GC anchor is 08:20, not a global :00/:15 grid


def test_early_close_profile_and_lagged_normalization():
    # Two short, explicitly configured synthetic sessions; not an exchange claim.
    calendar = SessionCalendar(eth_open='23:59', eth_close='00:03', rth_open='00:00', rth_close='00:02', breaks=[])
    first = path([.01, .02, .03, .04], local_at(date(2026,1,4),'23:59'))
    second = path([.1]*4, local_at(date(2026,1,5),'23:59'))
    rows = run(first + second, calendar)
    assert rows[3].session_complete
    assert rows[3].profile_variance_share is None
    assert rows[4].profile_variance_share == pytest.approx(1/30)
    assert rows[4].profile_volatility_share == pytest.approx(math.sqrt(1/30))
    assert rows[4].profile_reference_sessions == 1
    assert rows[4].profile_reference_through == first[-1].end
    assert sum(r.profile_variance_share for r in rows[4:]) == pytest.approx(1)
    assert run(first + second[:1], calendar)[-1] == rows[4]
    changed = second[:1] + path([.5]*3, second[1].timestamp)
    assert run(first + changed, calendar)[4] == rows[4]
    assert rows[-1].rv_1m == pytest.approx(.04)


def test_profile_excludes_incomplete_and_zero_denominator():
    calendar = SessionCalendar(eth_open='23:59', eth_close='00:03', rth_open='00:00', rth_close='00:02', breaks=[])
    first = path([0]*4, local_at(date(2026,1,4),'23:59'))
    second = path([.1]*4, local_at(date(2026,1,5),'23:59'))
    assert run(first + second, calendar)[-1].profile_variance_share is None
    partial = run(first[1:] + second, calendar)[-1]
    assert partial.profile_reference_sessions == 0


def test_closed_calendar_and_dst():
    calendar = SessionCalendar(overrides={'2026-01-05': {'closed': True}})
    with pytest.raises(ValueError, match='calendar'):
        run(path([0]), calendar)
    for day in (date(2026,3,9), date(2026,11,2)):
        start = local_at(day-timedelta(days=1), '18:00')
        assert run(path([.01], start))[0].prefix_complete


def test_cli_fixture_report_and_cutoff(tmp_path):
    from scripts.generate_synthetic_examples import generate

    generate(tmp_path / 'data')
    cmd = [sys.executable, '-m', 'backtester', 'volatility', '--data',
           str(tmp_path / 'data/synthetic_NQ_1m.csv'), '--symbol', 'NQ',
           '--as-of', '2026-01-04T23:05:00Z']
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload['input_price_basis'] == 'raw'
    assert payload['data_sha256']
    row = payload['records'][-1]
    assert row['observed_bars'] == 5
    assert row['timestamp'] == '2026-01-04T23:05:00+00:00'
    assert row['prefix_complete'] and row['samples_5m'] == 1
    assert row['tbpv'] is None



def test_early_close_overrides_define_completeness():
    calendar = SessionCalendar(overrides={'2026-01-05': {'eth_close': '13:00', 'rth_close': '13:00'}})
    bars = day_bars(calendar=calendar)
    row = run(bars, calendar)[-1]
    assert row.session_complete
    assert row.expected_bars_to_now == 1140
    assert row.rv_rth == 0 and row.rv_post_rth is None


def test_coarse_boundary_returns_and_tails():
    calendar = SessionCalendar(eth_open='23:40',eth_close='00:20',rth_open='00:00',rth_close='00:10',breaks=[])
    bars = path([.01]*40, local_at(date(2026,1,4),'23:40'))
    row = run(bars, calendar)[-1]
    assert row.session_complete
    # 20m overnight + 10m RTH + 10m post-RTH: eight 5m blocks, one 15m block.
    assert row.rv_5m == pytest.approx(8*.05**2)
    assert row.rv_15m == pytest.approx(.15**2)
    assert row.covered_minutes_15m == 15
    # BPV pairs exclude the two segment boundaries (40 - 3 pairs).
    assert row.bpv == pytest.approx(math.pi/2 * 37*.0001)


def test_real_roll_selection_feeds_constituent_measurements():
    calendar = SessionCalendar()
    old = path([0]*2)
    new = [replace(b,contract='ESH27',open=1000,high=1000,low=1000,close=1000) for b in old]
    panel = [b for pair in zip(old,new) for b in pair]
    series = ContinuousSeries(calendar,RollConfig(initial_contract='ESZ26',
                              expirations={'ESZ26':'2026-01-10','ESH27':'2026-03-20'}))
    selected = list(series.select(panel))
    assert selected[0].roll is not None
    assert selected[0].research.close == 100
    row = run([s.raw for s in selected])[-1]
    assert row.contract == 'ESH27' and row.rv_1m == 0


def test_profile_never_trains_on_roll_session():
    calendar = SessionCalendar(eth_open='23:59',eth_close='00:03',rth_open='00:00',rth_close='00:02',breaks=[])
    first = path([.01]*4, local_at(date(2026,1,4),'23:59'))
    first[2:] = [replace(b,contract='ESH27') for b in first[2:]]
    second = path([.02]*4, local_at(date(2026,1,5),'23:59'),contract='ESH27')
    assert run(first+second,calendar)[-1].profile_reference_sessions == 0


def test_profile_does_not_pool_different_schedules():
    calendar = SessionCalendar(eth_open='23:59',eth_close='00:03',rth_open='00:00',rth_close='00:02',breaks=[],
                               overrides={'2026-01-05': {'eth_close':'00:02','rth_close':'00:01'}})
    first = path([.01]*3, local_at(date(2026,1,4),'23:59'))
    second = path([.02]*4, local_at(date(2026,1,5),'23:59'))
    assert run(first+second,calendar)[-1].profile_reference_sessions == 0
