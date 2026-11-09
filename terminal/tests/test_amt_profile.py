from collections import defaultdict
from datetime import datetime, timezone
from fractions import Fraction
import random

import pytest
from fastapi.testclient import TestClient

from terminal.amt.model import Bar
from terminal.amt.profile import VOLUME_SCALE, make_profile, nodes, value_area, weights
from terminal.api import app, continuous_store, store
from terminal.continuous import build
from terminal.tests.test_continuous_terminal import make_inputs


def bar(low, high, close, volume):
    return Bar(datetime(2026, 3, 13, tzinfo=timezone.utc), low, high, close, volume)


@pytest.mark.parametrize('method', ['hlc3', 'uniform'])
@pytest.mark.parametrize('width', [1, 3, 16])
def test_allocation_matches_independent_tick_iteration(method, width):
    rng = random.Random(3)
    bars = [bar(lo, lo + span, lo + span // 2, rng.randrange(100))
            for lo, span in ((rng.randrange(-15, 15), rng.randrange(24)) for _ in range(100))]
    reference = defaultdict(Fraction)
    for b in bars:
        if method == 'uniform':
            for tick in range(b.low, b.high + 1):
                reference[tick // width] += Fraction(b.volume, b.high - b.low + 1)
        else:
            reference[round(Fraction(b.low + b.high + b.close, 3)) // width] += b.volume
    actual = weights(bars, method, width)
    assert {i: v for i, v in actual.items() if v} == {i: v for i, v in reference.items() if v}
    assert sum(actual.values()) == sum(b.volume for b in bars)
    profile = make_profile(bars, method, width, Fraction(7, 10), 1, .01, True)
    assert sum(row['volume_units'] for row in profile['rows']) == profile['total_volume'] * VOLUME_SCALE
    assert profile == make_profile(bars[::-1], method, width, Fraction(7, 10), 1, .01, True)


def test_value_area_and_tie_rules():
    assert value_area({0: 3, 1: 8, 2: 3}, 2, Fraction(7, 10)) == {
        'poc': {'low_tick': 2, 'high_tick': 3}, 'val_tick': 0, 'vah_tick': 3, 'included_fraction': 11/14}
    assert value_area({0: 7, 1: 7, 2: 1, 3: 1}, 1, Fraction(1, 2))['poc']['low_tick'] == 1
    assert value_area({0: 7, 1: 0, 2: 7}, 1, Fraction(1))['poc']['low_tick'] == 0
    assert value_area({}, 1, Fraction(7, 10)) is None


def test_nodes_and_transport_remainder():
    found = nodes(dict(enumerate([1, 9, 2, 8, 1])), 1, 0, .1)
    assert [row['low_tick'] for row in found['hvn']] == [1, 3]
    assert [row['low_tick'] for row in found['lvn']] == [2]
    result = make_profile([bar(0, 2, 1, 1)], 'uniform', 1, Fraction(7, 10), 0, 0, False)
    assert [row['volume_units'] for row in result['rows']] == [333334, 333333, 333333]


@pytest.fixture
def amt_client(tmp_path, monkeypatch):
    release, cleaned = make_inputs(tmp_path, missing=True, extended=True)
    derived = tmp_path / 'continuous'
    build(release, cleaned, derived)
    monkeypatch.setenv('NQ_DATA_ROOT', str(release))
    monkeypatch.setenv('NQ_CONTINUOUS_ROOT', str(derived))
    store.cache_clear()
    continuous_store.cache_clear()
    with TestClient(app) as client:
        yield client
    store.cache_clear()
    continuous_store.cache_clear()


def test_profile_cutoff_quality_and_provenance(amt_client):
    params = dict(contract='NQH26', session='2026-03-13', display='RTH',
                  as_of='2026-03-13T14:31:30Z', method='uniform', sensitivity='true')
    response = amt_client.get('/api/amt/profile', params=params)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['coverage']['observed_minutes'] == 1
    assert data['profile']['total_volume'] == 10
    assert data['coverage']['sessions'][0]['status'] == 'developing'
    assert data['profile']['sensitivity']['method'] == 'hlc3'
    assert data['source']['strict_eligible'] is False
    assert data['cutoff']['publication_verified'] is False
    assert data['profile']['classification'] == 'ohlcv_uniform_volume_estimate'
    params.update(as_of='2026-03-13T14:31:00Z')
    assert amt_client.get('/api/amt/profile', params=params).json()['profile'] == data['profile']


@pytest.mark.parametrize('overrides', [
    dict(row_ticks=0), dict(method='trade_exact'), dict(replay='true'), dict(extra='1'),
    dict(as_of='2026-03-13T14:30'), dict(as_of='1773412260'), dict(session='2026-03-13T00:00:00'), dict(value_fraction='nan'), dict(scope='range'),
    dict(contract='NQ1! Adjusted', as_of='2026-03-13T14:31:00Z'),
    dict(scope='range', start='2026-03-12', end='2026-03-19', contract='NQ1! Raw'),
    dict(scope='range', start='2026-03-12', end='2026-03-19', contract='NQ1! Adjusted'),
])
def test_profile_rejects_unsafe_or_invalid_requests(amt_client, overrides):
    params = dict(contract='NQH26', session='2026-03-13') | overrides
    assert amt_client.get('/api/amt/profile', params=params).status_code == 422


@pytest.mark.parametrize('corruption', ['foreign_contract', 'duplicate', 'off_grid', 'future'])
def test_observation_guard_rejects_inconsistent_source_rows(amt_client, monkeypatch, corruption):
    from datetime import timedelta
    from terminal.data import ResearchStore

    original = ResearchStore.query

    def query(self, sql, params=()):
        rows = original(self, sql, params)
        if 'NULL AS adjustment_block_id' not in sql:
            return rows
        if corruption == 'foreign_contract':
            rows[0]['source_contract'] = 'NQM26'
        elif corruption == 'duplicate':
            rows.insert(0, rows[0].copy())
        elif corruption == 'off_grid':
            rows[0]['high'] += .1
        else:
            rows[0]['timestamp_utc'] += timedelta(minutes=5)
        return rows

    monkeypatch.setattr(ResearchStore, 'query', query)
    response = amt_client.get('/api/amt/profile', params=dict(
        contract='NQH26', session='2026-03-13', as_of='2026-03-13T14:31:00Z'))
    assert response.status_code == 422, response.text


def test_amt_rejects_changed_verified_files(amt_client):
    params = dict(contract='NQH26', session='2026-03-13')
    assert amt_client.get('/api/amt/profile', params=params).status_code == 200
    with (store().root / 'research.parquet').open('ab') as file:
        file.write(b'changed after verification')
    response = amt_client.get('/api/amt/profile', params=params)
    assert response.status_code == 503
    assert 'changed after verification' in response.text
