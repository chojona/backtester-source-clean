from datetime import date, datetime, timedelta, timezone
from fractions import Fraction

from terminal.amt.model import Bar, session_bounds, trading_date
from terminal.amt.source import Sample
from terminal.amt.tpo import initial_balance, make_tpo, period_letter
from terminal.tests.test_amt_profile import amt_client  # noqa: F401


def test_calendar_dst_evening_attribution_and_rth():
    friday, monday = date(2026, 3, 6), date(2026, 3, 9)
    assert session_bounds(friday, 'Globex')[0] == datetime(2026, 3, 5, 23, tzinfo=timezone.utc)
    open_, close = session_bounds(monday, 'Globex')
    assert open_ == datetime(2026, 3, 8, 22, tzinfo=timezone.utc)
    assert close - open_ == timedelta(hours=23)
    assert trading_date(open_) == monday
    assert trading_date(open_ - timedelta(minutes=1)) == date(2026, 3, 8)
    assert session_bounds(friday, 'RTH')[0].hour == 14
    assert session_bounds(monday, 'RTH')[0].hour == 13
    assert session_bounds(date(2026, 11, 2), 'RTH')[0].hour == 14


def test_period_unions_missing_partial_and_poc_tie():
    day = date(2026, 3, 9)
    start, _ = session_bounds(day, 'RTH')
    bars = [Bar(start + timedelta(minutes=i), low, high, high, 0)
            for i, low, high in [(0, 1, 2), (1, 2, 4), (60, 3, 4)]]
    cutoff = start + timedelta(minutes=61)
    sample = Sample(day, bars, {}, None, 1380)
    data = make_tpo([sample], cutoff, 'RTH', 1, 30, Fraction(7, 10), 'letters', 60)
    assert [row['count'] for row in data['rows']] == [1, 1, 2, 2]
    assert data['value']['poc']['low_tick'] == 3
    assert [p['occupied_rows'] for p in data['periods']] == [4, 0, 2]
    assert [p['partial'] for p in data['periods']] == [False, False, True]
    assert [p['missing_elapsed_minutes'] for p in data['periods']] == [28, 30, 0]
    assert [p['letter'] for p in data['periods']] == ['A', 'B', 'C']
    assert period_letter(52) == 'AA'
    assert data['initial_balance'][0]['complete'] is False
    assert data['initial_balance'][0]['missing_elapsed_minutes'] == 58


def test_initial_balance_boundary():
    day = date(2026, 3, 9)
    start, _ = session_bounds(day, 'RTH')
    end = start + timedelta(minutes=60)
    bars = [Bar(start + timedelta(minutes=i), 2, 8, 3, 1) for i in range(60)]
    sample = Sample(day, bars + [Bar(end, 0, 99, 3, 1)], {}, None, 1380)
    ib = initial_balance(sample, end, 60)
    assert (ib['low_tick'], ib['high_tick'], ib['complete']) == (2, 8, True)


def test_api_tpo_developing_only_includes_closed_bars(amt_client):
    params = dict(contract='NQH26', session='2026-03-13', display='RTH',
                  as_of='2026-03-13T14:31:59Z', representation='blocks')
    response = amt_client.get('/api/amt/tpo', params=params)
    assert response.status_code == 200, response.text
    tpo = response.json()['tpo']
    assert tpo['classification'] == 'ohlcv_bar_range_tpo_estimate'
    assert len(tpo['periods']) == 3 and tpo['periods'][-1]['partial']
    assert [p['observed_minutes'] for p in tpo['periods'][:2]] == [0, 0]
    assert tpo['periods'][-1]['observed_minutes'] == 1
    assert tpo['periods'][-1]['ranges'] == [[448, 456]]
    assert tpo['initial_balance'][0]['complete'] is False
    assert amt_client.get('/api/amt/tpo', params=params | {'period_minutes': 2}).status_code == 422
