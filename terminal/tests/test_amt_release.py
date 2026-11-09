"""Reconcile display analytics directly to the existing sealed release."""
from datetime import datetime, timedelta
from fractions import Fraction

import pytest

from terminal.api import chart_store
from terminal.tests.test_api import client, db, identity  # noqa: F401


@pytest.mark.parametrize('method', ['hlc3', 'uniform'])
def test_release_profile_matches_independent_observation_allocation(db, client, identity, method):
    contract, day = identity
    source = db.query('''SELECT high,low,close,volume FROM bars WHERE trading_date=? AND contract=?
        AND eligible_full_session ORDER BY timestamp_utc''', [day.isoformat(), contract])
    response = client.get('/api/amt/profile', params=dict(contract=contract, session=str(day), method=method, row_ticks=4))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['coverage']['all_declared_sessions_complete'] is True
    assert data['coverage']['observed_minutes'] == len(source)
    actual = {row['low_tick']: row['volume_units'] for row in data['profile']['rows']}
    expected = dict.fromkeys(actual, Fraction())
    for row in source:
        low, high, close = (int(row[key] * 4) for key in ('low', 'high', 'close'))
        if method == 'hlc3':
            ticks = [round(Fraction(low + high + close, 3))]
        else:
            ticks = range(low, high + 1)
        for tick in ticks:
            expected[tick // 4 * 4] += Fraction(row['volume'], len(ticks))
    assert sum(actual.values()) == sum(row['volume'] for row in source) * 1_000_000
    assert all(abs(Fraction(actual[tick], 1_000_000) - expected[tick]) < Fraction(1, 1_000_000) for tick in actual)


def test_release_rth_vwap_and_tpo_reconcile_at_replay_cutoff(db, client, identity):
    contract, day = identity
    snap = db.snapshot(contract, day, display='RTH')
    prefix = snap['bars'][:67]
    cutoff = datetime.fromtimestamp(prefix[-1]['available_at'], tz=datetime.fromisoformat(snap['as_of']).tzinfo)
    params = dict(contract=contract, session=str(day), display='RTH', as_of=cutoff.isoformat(), replay=True, row_ticks=4)
    response = client.get('/api/amt/tpo', params=params | {'representation': 'letters'})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['coverage']['observed_minutes'] == 67
    periods = data['tpo']['periods']
    assert [p['observed_minutes'] for p in periods] == [30, 30, 7]
    assert [p['partial'] for p in periods] == [False, False, True]
    ib = data['tpo']['initial_balance'][0]
    assert ib['complete']
    assert ib['high_tick'] == max(row['high'] for row in prefix[:60]) * 4
    assert ib['low_tick'] == min(row['low'] for row in prefix[:60]) * 4
    for i, period in enumerate(periods):
        occupied = {tick for row in prefix[i * 30:(i + 1) * 30]
                    for tick in range(int(row['low']), int(row['high']) + 1)}
        assert period['occupied_rows'] == len(occupied)
    vwap_query = {key: value for key, value in params.items() if key != 'row_ticks'}
    response = client.get('/api/amt/vwap', params=vwap_query)
    assert response.status_code == 200, response.text
    points = response.json()['vwap']['points']
    assert len(points) == len(prefix)
    assert all(p['available_at'] <= cutoff.timestamp() for p in points)
    volume = sum(row['volume'] for row in prefix)
    mean = sum((row['high'] + row['low'] + row['close']) / 3 * row['volume'] for row in prefix) / volume
    assert points[-1]['vwap'] == pytest.approx(mean)


def test_release_context_prior_uses_completed_compatible_value(db, client):
    row = db.query('''SELECT a.trading_date, a.selected_contract, b.trading_date AS prior FROM eligibility a
        JOIN eligibility b ON a.prior_candidate_date=b.trading_date AND a.selected_contract=b.selected_contract
        WHERE a.eligible_full_session AND b.eligible_full_session ORDER BY a.trading_date DESC LIMIT 1''')[0]
    params = dict(contract=row['selected_contract'], session=row['trading_date'], display='RTH', row_ticks=4)
    context = client.get('/api/amt/context', params=params).json()
    reference = client.get('/api/amt/profile', params=params | {'session': row['prior']}).json()
    assert context['previous']['status'] == 'available'
    assert context['previous']['value'] == reference['profile']['value']
    current = context['context']['value']
    previous = reference['profile']['value']
    assert context['context']['poc_migration_ticks'] == current['poc']['low_tick'] - previous['poc']['low_tick']


def test_release_continuous_preserves_price_blocks_and_raw_volume(db, client, identity):
    import os
    if not os.getenv('NQ_CONTINUOUS_ROOT'):
        pytest.skip('Requires external sealed continuous release')
    contract, day = identity
    adjusted = chart_store(db, 'NQ1! Adjusted')
    for symbol in ('NQ1! Raw', 'NQ1! Adjusted'):
        response = client.get('/api/amt/profile', params=dict(contract=symbol, session=str(day), row_ticks=4))
        assert response.status_code == 200, response.text
        data = response.json()
        expected = adjusted.query(symbol, '''SELECT sum(volume) AS volume, min(source_contract) AS contract
            FROM bars WHERE trading_date=? AND eligible_full_session''', [str(day)])[0]
        assert data['profile']['total_volume'] == expected['volume']
        assert data['coverage']['sessions'][0]['lineage']['source_contract'] == expected['contract'] == contract
        assert data['source']['retrospective_prices'] == (symbol == 'NQ1! Adjusted')
    blocks = adjusted.query('NQ1! Adjusted', '''SELECT adjustment_block_id, min(trading_date) AS first, max(trading_date) AS last
        FROM bars WHERE eligible_full_session GROUP BY 1 ORDER BY 1''')
    for before, after in zip(blocks, blocks[1:]):
        start, end = before['last'], after['first']
        if datetime.fromisoformat(end) - datetime.fromisoformat(start) < timedelta(days=31):
            response = client.get('/api/amt/vwap', params=dict(contract='NQ1! Adjusted', session=end,
                anchor=start + 'T15:00:00Z', scope='manual'))
            assert response.status_code == 422
            assert 'independent adjustment blocks' in response.text
            break
    else:
        pytest.skip('No two contributing independent blocks within the manual VWAP range bound')
