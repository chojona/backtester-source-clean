from datetime import date, timedelta
from math import sqrt

import pytest

from terminal.amt.model import Bar, session_bounds
from terminal.amt.source import Sample
from terminal.amt.vwap import make_vwap
from terminal.tests.test_amt_profile import amt_client  # noqa: F401


def test_weighted_moments_zeros_disconnection_and_cutoff():
    day = date(2026, 3, 9)
    start, _ = session_bounds(day, 'RTH')
    bars = [Bar(start + timedelta(minutes=i), low, high, close, weight)
            for i, low, high, close, weight in [
                (0, 8, 12, 12, 0), (1, 10, 12, 11, 3), (3, 14, 16, 15, 1),
                (4, 300, 300, 300, 90)]]
    sample = Sample(day, bars, {}, None, 1380)
    vwap = make_vwap([sample], None, start + timedelta(minutes=4), 2)
    assert [p['break_before'] for p in vwap['points']] == [True, False, True]
    assert [p['vwap'] for p in vwap['points']] == [None, 2.75, 3.0]
    assert vwap['points'][-1]['upper'] == pytest.approx(3 + 2 * sqrt(3 / 16))
    assert vwap['points'][-1]['lower'] == pytest.approx(3 - 2 * sqrt(3 / 16))
    anchored = make_vwap([sample], start + timedelta(minutes=1, seconds=1), start + timedelta(minutes=4), 1)
    assert [p['vwap'] for p in anchored['points']] == [3.75]


def test_vwap_emission_window_does_not_reset_moments(amt_client):
    params = dict(contract='NQM26', session='2026-03-19', scope='week', display='RTH')
    response = amt_client.get('/api/amt/vwap', params=params)
    assert response.status_code == 200, response.text
    full = response.json()['vwap']['points']
    assert full[0]['trading_date'] == '2026-03-17'
    paged = amt_client.get('/api/amt/vwap', params=params | {'points_from': '2026-03-19T13:31:00Z'}).json()
    assert paged['vwap']['points'] == [p for p in full if p['trading_date'] == '2026-03-19']
    assert paged['vwap']['points'][0]['volume'] > 10


def test_manual_anchor_inclusive_minute_and_causal_restrictions(amt_client):
    params = dict(contract='NQH26', session='2026-03-13', scope='manual', display='RTH',
                  anchor='2026-03-13T14:30:00Z', as_of='2026-03-13T14:31:59Z')
    data = amt_client.get('/api/amt/vwap', params=params).json()
    assert len(data['vwap']['points']) == 1
    assert data['vwap']['points'][0]['vwap'] == 113
    assert amt_client.get('/api/amt/vwap', params=params | {'anchor': '2026-03-13T14:30:01Z'}).json()['vwap']['points'] == []
    for overrides in [
        dict(anchor='2026-03-13T14:32:00Z'),
        dict(anchor='2026-03-13T14:30:00'),
        dict(contract='NQ1! Adjusted'),
    ]:
        assert amt_client.get('/api/amt/vwap', params=params | overrides).status_code == 422
    cross = dict(contract='NQ1! Adjusted', session='2026-03-19', scope='manual',
                 anchor='2026-03-12T14:30:00Z')
    assert amt_client.get('/api/amt/vwap', params=cross).status_code == 422
