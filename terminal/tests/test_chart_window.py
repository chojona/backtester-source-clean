"""Constructed-data and optional sealed-release tests for bounded chart history."""
from datetime import datetime
import os

from fastapi.testclient import TestClient
import pytest

from terminal.api import app, continuous_store, store
from terminal.continuous import build
from terminal.data import FRAMES
from terminal.tests.test_continuous_terminal import make_inputs

PATH = '/api/chart/window'


@pytest.fixture(scope='module')
def fixture_release(tmp_path_factory):
    root = tmp_path_factory.mktemp('chart-window')
    source, cleaned = make_inputs(root, missing=True, extended=True)
    continuous = root / 'continuous'
    build(source, cleaned, continuous)
    return source, continuous


@pytest.fixture
def client(fixture_release, monkeypatch):
    source, continuous = fixture_release
    monkeypatch.setenv('NQ_DATA_ROOT', str(source))
    monkeypatch.setenv('NQ_CONTINUOUS_ROOT', str(continuous))
    store.cache_clear()
    continuous_store.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    store.cache_clear()
    continuous_store.cache_clear()


def get(client, contract='NQ1! Raw', **params):
    response = client.get(PATH, params={'contract': contract, **params})
    assert response.status_code == 200, response.text[:500]
    return response.json()


@pytest.mark.parametrize('frame', FRAMES)
@pytest.mark.parametrize('display', ['Globex', 'RTH'])
@pytest.mark.parametrize('contract,session', [('NQH26', '2026-03-13'), ('NQ1! Raw', '2026-03-16'),
                                            ('NQ1! Adjusted', '2026-03-16')])
def test_window_matches_session_aggregation(client, frame, display, contract, session):
    params = dict(contract=contract, session=session, timeframe=frame, display=display,
                  opening_minutes=15, deviations=2)
    page = get(client, **params)
    snapshot = client.get('/api/snapshot', params=params).json()
    actual = [b for b in page['bars'] if b['trading_date'] == session]
    if contract == 'NQH26':
        for bar in actual:
            assert bar.pop('source_contract') == contract
            bar.pop('trading_date')
        assert page['session_context'][session]['previous'] == snapshot['previous']
    assert actual == snapshot['bars']
    assert page['series']['release_id']
    assert page['retrospective'] == contract.endswith('Adjusted')
    assert page['provenance']['strict_eligible'] is False


def test_pagination_crosses_roll_and_empty_session(client):
    initial = get(client, session='2026-03-16', start_sessions=1)
    assert initial['has_older'] and initial['has_newer']
    assert initial['rolls'][0]['overlap']['status'] == 'unresolved'
    older = get(client, cursor=initial['older_cursor'])
    newer = get(client, cursor=initial['newer_cursor'])
    assert older['session_dates'] == ['2026-03-12', '2026-03-13']
    assert newer['session_dates'] == ['2026-03-17', '2026-03-18', '2026-03-19']
    assert not older['has_older'] and not newer['has_newer']
    assert not any(bar['trading_date'] == '2026-03-18' for bar in newer['bars'])
    assert {s['trading_date'] for s in newer['unavailable_sessions']} == {'2026-03-18'}
    assert max(bar['time'] for bar in older['bars']) < min(bar['time'] for bar in initial['bars'])
    assert max(bar['time'] for bar in initial['bars']) < min(bar['time'] for bar in newer['bars'])
    # Independently recompute the session reset and last cumulative HLC3 VWAP.
    day = [bar for bar in older['bars'] if bar['trading_date'] == '2026-03-13']
    assert day[0]['vwap'] == (day[0]['high'] + day[0]['low'] + day[0]['close']) / 3
    assert day[-1]['vwap'] == pytest.approx(
        sum((b['high'] + b['low'] + b['close']) / 3 * b['volume'] for b in day) /
        sum(b['volume'] for b in day))
    adjusted = get(client, 'NQ1! Adjusted', session='2026-03-19', timeframe='daily')
    assert len({bar['adjustment_block_id'] for bar in adjusted['bars']}) == 2
    assert all(bar['volume'] > 0 for bar in adjusted['bars'])


@pytest.mark.parametrize('change', [
    {'contract': 'NQ1! Adjusted'}, {'contract': 'NQH26'}, {'timeframe': '5m'},
    {'display': 'RTH'}, {'opening_minutes': 31}, {'deviations': 2}, {'sessions': 19},
    {'as_of': '2026-03-16T14:00:00Z'}, {'start_sessions': 1}, {'session': '2026-03-16'},
])
def test_cursor_rejects_parameter_changes(client, change):
    initial = get(client, session='2026-03-16', start_sessions=1)
    response = client.get(PATH, params={'contract': 'NQ1! Raw', 'cursor': initial['older_cursor'], **change})
    assert response.status_code == 422


@pytest.mark.parametrize('token', ['', 'a', 'bad?', 'A' * 256, 'A' * 257])
def test_malformed_cursor(client, token):
    assert client.get(PATH, params={'contract': 'NQ1! Raw', 'cursor': token}).status_code == 422


def test_cursor_rejects_tampering_and_restart(client, monkeypatch):
    initial = get(client, session='2026-03-16', start_sessions=1)
    token = initial['older_cursor']
    corrupt = ('B' if token[0] == 'A' else 'A') + token[1:]
    assert client.get(PATH, params={'contract': 'NQ1! Raw', 'cursor': corrupt}).status_code == 422
    monkeypatch.setattr('terminal.chart_window._CURSOR_KEY', b'a different worker key')
    assert client.get(PATH, params={'contract': 'NQ1! Raw', 'cursor': token}).status_code == 422


def test_cutoff_filters_prices_partial_buckets_and_roll_overlap(client):
    cutoff = '2026-03-16T13:33:30Z'
    page = get(client, session='2026-03-19', timeframe='5m', as_of=cutoff)
    assert page['session_dates'][-1] == '2026-03-16'
    assert not page['has_newer']
    assert page['as_of'] == '2026-03-16T13:33:30+00:00'
    assert page['bars'][-1]['partial']
    assert page['bars'][-1]['source_count'] == 3
    assert all(b['available_at'] <= datetime.fromisoformat(cutoff).timestamp() for b in page['bars'])
    assert all(not b['partial'] for b in page['bars'] if b['trading_date'] < '2026-03-16')
    assert all('eligible_full_session' not in b for b in page['bars'])
    assert page['rolls'] and 'overlap' not in page['rolls'][0]
    assert page['unavailable_sessions'] == []
    for invalid in [
        {'contract': 'NQ1! Adjusted', 'as_of': cutoff},
        {'contract': 'NQ1! Raw', 'as_of': '2026-03-16T13:33:30'},
    ]:
        assert client.get(PATH, params=dict(session='2026-03-16', **invalid)).status_code == 422


def test_window_fails_closed_after_verified_files_change(client, monkeypatch):
    get(client, session='2026-03-16')
    db = store()
    # A changed file stamp without modifying the fixture shared by other tests.
    path = db.root / 'research.parquet'
    monkeypatch.setitem(db._stamps, path, ())
    response = client.get(PATH, params={'contract': 'NQH26', 'session': '2026-03-13'})
    assert response.status_code == 503


@pytest.mark.skipif(not (os.getenv('NQ_DATA_ROOT') and os.getenv('NQ_CONTINUOUS_ROOT')),
                    reason='Requires both external sealed datasets')
def test_release_window_cap_and_snapshot_reconciliation():
    # No market observations or licensed fixture bytes are emitted by the test.
    store.cache_clear()
    continuous_store.cache_clear()
    with TestClient(app) as client:
        sessions = client.get('/api/sessions', params={'contract': 'NQ1! Raw', 'limit': 30}).json()
        session = sessions[12]['trading_date']
        page = get(client, session=session)
        assert 0 < len(page['bars']) <= 2500
        assert page['has_older'] and page['has_newer']
        source = client.get('/api/snapshot', params={'contract': 'NQ1! Raw', 'session': session}).json()
        assert [b for b in page['bars'] if b['trading_date'] == session] == source['bars']
        adjacent = get(client, cursor=page['older_cursor'])
        assert set(adjacent['session_dates']).isdisjoint(page['session_dates'])
        daily = get(client, 'NQ1! Adjusted', session=session, timeframe='daily', sessions=250)
        assert len(daily['session_dates']) == 250
        assert len(daily['bars']) <= 250
    store.cache_clear()
    continuous_store.cache_clear()
