"""Integration checks use the licensed historical release, never invented candles.

Set NQ_DATA_ROOT to run these tests. A missing dataset is explicitly skipped.
"""
import math
import os
from datetime import date, datetime, timedelta

import duckdb
import pytest
from fastapi.testclient import TestClient

from terminal.api import app, store
from terminal.data import DataError, ResearchStore, FRAMES


@pytest.fixture(scope='module')
def db():
    root = os.getenv('NQ_DATA_ROOT')
    if not root:
        pytest.skip('Historical integration requires NQ_DATA_ROOT (no synthetic fallback)')
    return ResearchStore(root)


@pytest.fixture(scope='module')
def identity(db):
    s = db.sessions(None, None, None, 1, 0)[0]
    return s['contract'], date.fromisoformat(s['trading_date'])


@pytest.fixture(scope='module')
def full(db, identity):
    return db.snapshot(*identity)


@pytest.fixture
def client(db):
    app.dependency_overrides[store] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def params(identity, **kw):
    return {'contract': identity[0], 'session': identity[1].isoformat(), **kw}


def test_release_counts_and_provenance(db):
    p = db.provenance()
    assert p['summary']['eligible_bars'] == 2_141_265
    assert p['summary']['eligible_sessions'] == 1557
    assert p['strict_eligible'] is False
    assert len(p['hashes']) == 6
    assert all(len(h) == 64 for h in p['hashes'].values())
    assert sum(c['sessions'] for c in db.contracts()) == 1557


def test_seal_refuses_changed_artifact(db, tmp_path):
    # Deliberately invalid artifact bytes, never used as market data.
    (tmp_path / 'SUCCESS.json').write_text((db.root / 'SUCCESS.json').read_text())
    (tmp_path / 'research.parquet').write_bytes(b'corrupt')
    with pytest.raises(DataError, match='hash mismatch'):
        ResearchStore(tmp_path)


def test_exact_contract_and_eligibility_required(db, identity):
    with pytest.raises(DataError, match='exact contract'):
        db.snapshot('NQH10', identity[1])
    excluded = db.query('SELECT trading_date, selected_contract FROM eligibility WHERE NOT eligible_full_session LIMIT 1')[0]
    with pytest.raises(DataError):
        db.snapshot(excluded['selected_contract'], date.fromisoformat(excluded['trading_date']))


def test_full_session_matches_original_parquet(db, identity, full):
    with duckdb.connect() as c:
        source = c.execute('''SELECT epoch(CAST(timestamp_utc AS TIMESTAMPTZ))::BIGINT, open, high, low, close, volume
          FROM read_parquet(?) WHERE trading_date=? AND contract=? AND eligible_full_session IS TRUE
          ORDER BY timestamp_utc''', [str(db.root / 'research.parquet'), identity[1].isoformat(), identity[0]]).fetchall()
    assert len(source) == full['total_minutes'] == len(full['bars'])
    assert [tuple(b[k] for k in ('time', 'open', 'high', 'low', 'close', 'volume')) for b in full['bars']] == source
    assert all(a['time'] < b['time'] for a,b in zip(full['bars'], full['bars'][1:]))


@pytest.mark.parametrize('cursor', [0,1,17,929,945,961])
def test_replay_is_causal(db, identity, full, cursor):
    snap = db.snapshot(*identity, cursor=cursor)
    assert snap['bars'] == full['bars'][:cursor]
    assert snap['cursor'] == cursor
    assert snap['explorer']['total'] == cursor
    assert all(b['available_at'] <= datetime.fromisoformat(snap['as_of']).timestamp() for b in snap['bars'])
    known = full['bars'][:cursor]
    s = snap['stats']
    assert s['volume'] == sum(b['volume'] for b in known)
    assert s['high'] == max((b['high'] for b in known), default=None)
    assert s['low'] == min((b['low'] for b in known), default=None)
    if cursor:
        expected = sum(((b['high']+b['low']+b['close'])/3)*b['volume'] for b in known)/s['volume']
        assert s['vwap'] == pytest.approx(expected)
    else:
        assert s['open'] is None and s['close'] is None and s['or_high'] is None


@pytest.mark.parametrize('frame', FRAMES)
def test_partial_aggregation_uses_only_known_minutes(db, identity, full, frame):
    n=947
    snap=db.snapshot(*identity,frame,cursor=n)
    assert sum(b['source_count'] for b in snap['bars']) == n
    assert sum(b['volume'] for b in snap['bars']) == sum(b['volume'] for b in full['bars'][:n])
    assert snap['bars'][-1]['close'] == full['bars'][n-1]['close']
    assert snap['bars'][-1]['vwap'] == full['bars'][n-1]['vwap']
    assert snap['stats'] == db.snapshot(*identity,cursor=n)['stats']
    assert snap['bars'][-1]['partial'] == (frame != '1m')


def test_availability_at_close_and_timezones(db, identity, full):
    first = datetime.fromtimestamp(full['bars'][0]['time'], tz=__import__('datetime').timezone.utc)
    assert db.snapshot(*identity,as_of=first+timedelta(seconds=59))['cursor'] == 0
    assert db.snapshot(*identity,as_of=first+timedelta(seconds=60))['cursor'] == 1
    early = db.snapshot(*identity,as_of=first-timedelta(days=10))
    assert early['bars'] == [] and early['previous']['high'] is None
    with pytest.raises(DataError,match='timezone'):
        db.snapshot(*identity,as_of=datetime(2026,1,1))


def test_opening_range_not_visible_before_open(db, identity, full):
    from zoneinfo import ZoneInfo
    et=ZoneInfo('America/New_York')
    opening=datetime.combine(identity[1],datetime.min.time(),et).replace(hour=9,minute=30)
    before=db.snapshot(*identity,as_of=opening)
    assert before['stats']['or_high'] is None
    during=db.snapshot(*identity,as_of=opening+timedelta(minutes=7))
    assert during['stats']['or_complete'] is False
    known=[b for b in full['bars'] if opening.timestamp()<=b['time']<(opening+timedelta(minutes=7)).timestamp()]
    assert during['stats']['or_high'] == max(b['high'] for b in known)
    assert during['stats']['or_low'] == min(b['low'] for b in known)


def test_api_endpoints_and_bounds(client,identity):
    for route in ('snapshot','statistics','indicators'):
        r=client.get(f'/api/{route}',params=params(identity,cursor=5))
        assert r.status_code == 200, r.text
    assert client.get('/api/provenance').json()['verified']
    assert client.get('/api/rolls',params={'contract':identity[0]}).status_code==200
    assert client.get('/api/snapshot',params=params(identity,timeframe='2m')).status_code==422
    assert client.get('/api/snapshot',params=params(identity,cursor=99999)).status_code==422
    assert client.get('/api/snapshot',params=params(identity,as_of='2026-01-01T00:00:00')).status_code==422
    assert client.get('/api/snapshot',params=params(identity,contract="NQZ26' OR 1=1")).status_code==422
    assert client.get('/api/sessions',params={'limit':10000}).status_code==422
    assert client.get('/api/bars',params={'contract':identity[0],'start':'2016-01-01','end':'2026-01-01'}).status_code==422
    r=client.get('/api/bars',params={'contract':identity[0],'start':identity[1].isoformat(),'end':identity[1].isoformat(),'timeframe':'daily'})
    assert r.status_code==200 and len(r.json()['sessions'])==1


def test_explorer_pagination_and_cutoff(client,identity):
    r=client.get('/api/snapshot',params=params(identity,cursor=73,offset=50)).json()
    assert len(r['explorer']['rows'])==23
    assert r['explorer']['rows']==r['bars'][50:73]
    indicators=client.get('/api/indicators',params=params(identity,cursor=73)).json()
    assert indicators['as_of']==r['as_of']
    assert indicators['points'][-1]['vwap']==r['stats']['vwap']


def test_missing_configuration_is_actionable(monkeypatch):
    app.dependency_overrides.clear()
    store.cache_clear()
    monkeypatch.delenv('NQ_DATA_ROOT',raising=False)
    with TestClient(app) as c:
        r=c.get('/api/health')
    assert r.status_code==503 and 'NQ_DATA_ROOT' in r.json()['detail']
    store.cache_clear()


def test_realized_volatility_and_previous_levels(db, identity, full):
    known = full['bars']
    rv = sum(math.log(b['close']/a['close'])**2 for a,b in zip(known,known[1:]) if b['time']-a['time']==60)
    assert full['stats']['realized_volatility'] == pytest.approx(math.sqrt(rv)*100)
    prior = db.query("SELECT min(low) AS low, max(high) AS high FROM context WHERE trading_date=? AND contract=?",
                     [full['previous']['date'],identity[0]])[0]
    assert full['previous']['high'] == prior['high']
    assert full['previous']['low'] == prior['low']


@pytest.mark.parametrize('year',[2016,2020,2024,2026])
def test_historical_coverage_and_timezone_across_years(db,year):
    from zoneinfo import ZoneInfo
    sessions = db.sessions(None,date(year,1,1),date(year,12,31),1,0)
    assert sessions
    session=sessions[0]
    snap=db.snapshot(session['contract'],date.fromisoformat(session['trading_date']),cursor=1)
    assert snap['bars'][0]['available_at']-snap['bars'][0]['time']==60
    assert datetime.fromisoformat(snap['session_start']).tzinfo is not None
    et=datetime.fromisoformat(snap['session_start']).astimezone(ZoneInfo('America/New_York'))
    assert et.hour==18
