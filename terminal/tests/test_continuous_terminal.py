"""Constructed contract panels only; historical builds have separate QA reports."""
from datetime import date,datetime,timedelta,timezone
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import duckdb
import pytest
from fastapi.testclient import TestClient

from terminal.continuous import (build,choose,offsets,block_offsets,overlap_evidence,roll_open,
                                 SELECTION,literal)
from terminal.continuous_data import ContinuousStore
from terminal.data import DataError,digest

UTC=timezone.utc


def make_inputs(root, missing=False, extended=False):
    release=root/'source-release';cleaned=root/'source-cleaned'
    release.mkdir(parents=True);cleaned.mkdir()
    with duckdb.connect() as c:
        c.execute('''CREATE TABLE clean(timestamp_utc TIMESTAMPTZ,contract VARCHAR,open DOUBLE,high DOUBLE,
            low DOUBLE,close DOUBLE,volume BIGINT)''')
        stamp=datetime(2026,3,13,20,50,tzinfo=UTC)
        rows=[]
        for i in range(5):
            for contract,base in [('NQH26',100),('NQM26',110)]:
                if missing and i==2 and contract=='NQM26':continue
                rows.append((stamp+timedelta(minutes=i),contract,base+i,base+i+1,base+i-1,base+i,10+i))
        for i in range(3):
            rows.append((datetime(2026,3,16,13,30,tzinfo=UTC)+timedelta(minutes=i),'NQM26',115+i,116+i,114+i,115+i,20+i))
        if extended:
            for day, contract, first_minute, start_hour in (
                (12, 'NQH26', 0, 14), (13, 'NQH26', 0, 14),
                (16, 'NQM26', 4, 13), (17, 'NQM26', 0, 13), (19, 'NQM26', 0, 13),
            ):
                start = datetime(2026, 3, day, start_hour, 30, tzinfo=UTC)
                for minute in range(first_minute, 180):
                    price = 100 + day + (minute % 13) / 4
                    rows.append((start + timedelta(minutes=minute), contract,
                                 price, price + 1, price - 1, price, 10 + minute))
        c.executemany('INSERT INTO clean VALUES (?,?,?,?,?,?,?)',rows)
        c.execute(f'COPY clean TO {literal(cleaned/"nq-ohlcv-1m.parquet")} (FORMAT PARQUET)')
        c.execute('''CREATE TABLE sessions(trading_date VARCHAR, selected_contract VARCHAR, roll BOOLEAN,
            observed_minutes INTEGER, ordinary_candidate_minutes INTEGER,prior_candidate_date VARCHAR,
            calendar_status VARCHAR,certified_complete BOOLEAN,warmup_14_ready BOOLEAN,
            eligible_full_session BOOLEAN,quality_flags VARCHAR,absent_candidate_minutes INTEGER)''')
        c.executemany('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',[
            ('2026-03-13','NQH26',False,5,5,'2026-03-12','synthetic',False,False,True,'',0),
            ('2026-03-16','NQM26',True,3,4,'2026-03-13','synthetic',False,False,False,'ROLL_TRANSITION;MISSING',1)])
        if extended:
            c.execute("""UPDATE sessions SET observed_minutes=185, ordinary_candidate_minutes=185
                         WHERE trading_date='2026-03-13'""")
            c.execute("""UPDATE sessions SET observed_minutes=179, ordinary_candidate_minutes=180
                         WHERE trading_date='2026-03-16'""")
            c.executemany('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', [
                ('2026-03-12', 'NQH26', False, 180, 180, '2026-03-11', 'synthetic', False, False, True, '', 0),
                ('2026-03-17', 'NQM26', False, 180, 180, '2026-03-16', 'synthetic', False, False, True, '', 0),
                ('2026-03-18', 'NQM26', False, 0, 180, '2026-03-17', 'synthetic', False, False, False, 'MISSING', 180),
                ('2026-03-19', 'NQM26', False, 180, 180, '2026-03-18', 'synthetic', False, False, True, '', 0),
            ])
        c.execute('ALTER TABLE sessions ADD COLUMN full_grid_observed BOOLEAN')
        c.execute('UPDATE sessions SET full_grid_observed = eligible_full_session')
        c.execute(f'COPY sessions TO {literal(release/"session-eligibility.parquet")} (FORMAT PARQUET)')
        c.execute(f'COPY (SELECT * FROM sessions WHERE roll) TO {literal(release/"contract-rolls.parquet")} (FORMAT PARQUET)')
        c.execute('''CREATE TABLE selected AS SELECT c.*,s.*,
            FALSE AS boundary_unresolved FROM clean c JOIN sessions s
            ON CAST(timezone('America/New_York',timestamp_utc) AS DATE)::VARCHAR=s.trading_date
            AND c.contract=s.selected_contract''')
        c.execute(f'COPY selected TO {literal(release/"selected-observations-with-flags.parquet")} (FORMAT PARQUET)')
        if extended:
            c.execute(f'COPY (SELECT * FROM selected WHERE eligible_full_session) TO {literal(release/"research.parquet")} (FORMAT PARQUET)')
        c.execute('''CREATE TABLE gaps AS SELECT '2026-03-16' AS trading_date,'NQM26' AS contract,
            TIMESTAMPTZ '2026-03-16 13:33:00+00' AS start_utc,TIMESTAMPTZ '2026-03-16 13:34:00+00' AS end_exclusive_utc,
            1 AS minutes,'Unresolved' AS classification''')
        c.execute(f'COPY gaps TO {literal(release/"selected-gap-intervals.parquet")} (FORMAT PARQUET)')
    (cleaned/'SUCCESS.json').write_text('{}')
    summary = {'version': 'nq-ohlcv-research-v2.0.0', 'rolls': 1, 'policy': {'selection': SELECTION}}
    if extended:
        summary.update(source='formula-only test fixture', eligible_bars=725, eligible_sessions=4,
                       earliest_eligible_date='2026-03-12', latest_eligible_date='2026-03-19', excluded_sessions=2)
    (release/'summary.json').write_text(json.dumps(summary))
    (release/'input-bindings.json').write_text(json.dumps({str((cleaned/name).resolve()):digest(cleaned/name) for name in ['SUCCESS.json','nq-ohlcv-1m.parquet']}))
    (release/'SUCCESS.json').write_text(json.dumps({'version':'nq-ohlcv-research-v2.0.0','outputs':{p.name:digest(p) for p in release.iterdir()}}))
    return release,cleaned


@pytest.fixture(scope='module')
def artifacts(tmp_path_factory):
    root=tmp_path_factory.mktemp('continuous')
    release,cleaned=make_inputs(root)
    output=root/'derived'
    seal=build(release,cleaned,output)
    original=type('Original',(),{})()
    original.hashes=seal['specification']['inputs']
    original.contracts=lambda:[]
    store=ContinuousStore(output,original)
    return root,release,cleaned,output,seal,original,store


def test_chronological_fixed_calendar_selection():
    assert choose(date(2026,3,13))=='NQH26'
    assert choose(date(2026,3,16))=='NQM26'
    assert roll_open(date(2026,3,16))==datetime(2026,3,15,22,tzinfo=UTC)
    for year in (2010,2012,2020,2026):
        selections=[choose(date(year,1,1)+timedelta(days=i)) for i in range(365)]
        assert len(set(selections))==5


def test_adjustment_arithmetic_and_unresolved_blocks():
    assert offsets([10,-3])==[7,-3,0]
    assert offsets([10,None,-3])==[None,None,-3,0]
    local,blocks=block_offsets([10,None,-3])
    assert local==[10,0,-3,0]
    assert blocks==[0,0,1,1]
    decision=datetime(2026,3,15,22,tzinfo=UTC)
    rows=[(decision-timedelta(minutes=i+2),100,110,10,10) for i in range(5)]
    assert overlap_evidence(rows,decision)['gap']==10
    rows[2]=(rows[2][0]-timedelta(seconds=1),100,110,10,10)
    assert overlap_evidence(rows,decision)['gap'] is None


def test_source_preservation_and_volume(artifacts):
    _,release,cleaned,output,seal,_,store=artifacts
    with duckdb.connect() as c:
        raw=c.execute(f'SELECT * FROM read_parquet({literal(output/"raw.parquet")}) ORDER BY timestamp_utc').fetchall()
        columns=[d[0] for d in c.description]
        raw=[dict(zip(columns,r)) for r in raw]
        adjusted=c.execute(f'SELECT open,high,low,close,volume,adjustment_offset,source_contract FROM read_parquet({literal(output/"adjusted.parquet")}) ORDER BY timestamp_utc').fetchall()
    assert len(raw)==8
    for r,a in zip(raw,adjusted):
        for i,key in enumerate(['open','high','low','close']):
            assert r[key]==r['raw_'+key]
            assert a[i]==r[key]+a[5]
        assert a[4]==r['volume']
        assert r['performance_eligible'] is False
        assert r['strict_eligible'] is False
        if r['contract']=='NQM26':
            assert r['same_contract_log_return'] is None
    assert raw[5]['same_contract_log_return'] is None
    assert raw[1]['same_contract_log_return'] is not None
    assert store.rolls[0]['overlap']['gap']==10
    assert store.quality['source_prices_and_volume_preserved']
    for name,h in seal['specification']['inputs'].items():
        if name.startswith('cleaned/'):assert digest(cleaned/name.removeprefix('cleaned/'))==h
        else:assert digest(release/name)==h


def test_missing_overlap_no_invented_adjustment(tmp_path):
    release,cleaned=make_inputs(tmp_path,missing=True)
    output=tmp_path/'derived'
    build(release,cleaned,output)
    adjustments=json.loads((output/'adjustment-manifest.json').read_text())['segments']
    assert adjustments[0]['global_offset'] is None
    assert adjustments[0]['block_id']!=adjustments[1]['block_id']
    quality=json.loads((output/'quality-report.json').read_text())
    assert quality['supported_rolls']==0
    assert quality['adjustment_across_unresolved_rolls'] is False


def test_reproducible_artifacts_and_source_protection(artifacts):
    root,release,cleaned,output,seal,_,_=artifacts
    repeated=build(release,cleaned,root/'rebuilt')
    assert repeated==seal
    assert build(release,cleaned,output)==seal
    with pytest.raises(DataError,match='outside'):
        build(release,cleaned,release/'derived')


def test_continuous_seal_refuses_unlisted_or_changed_outputs(artifacts, tmp_path):
    _, _, _, output, seal, original, _ = artifacts
    copied = tmp_path / 'copy'
    shutil.copytree(output, copied)
    manifest = copied / 'SUCCESS.json'
    incomplete = {**seal, 'outputs': {k: v for k, v in seal['outputs'].items() if k != 'raw.parquet'}}
    manifest.write_text(json.dumps(incomplete))
    with pytest.raises(DataError, match='missing output hashes: raw.parquet'):
        ContinuousStore(copied, original)

    manifest.write_text(json.dumps(seal))
    gap_file = copied / 'selected-gap-intervals.parquet'
    gap_file.write_bytes(b'changed fixture')
    with pytest.raises(DataError, match='Changed continuous artifact'):
        ContinuousStore(copied, original)
    rewritten = {**seal, 'outputs': {**seal['outputs'], gap_file.name: digest(gap_file)}}
    manifest.write_text(json.dumps(rewritten))
    with pytest.raises(DataError, match='differs from its bound source'):
        ContinuousStore(copied, original)


def test_replay_causality_and_adjusted_refusal(artifacts):
    store=artifacts[-1]
    full=store.snapshot('NQ1! Raw',date(2026,3,16))
    replay=store.snapshot('NQ1! Raw',date(2026,3,16),cursor=1)
    assert len(replay['bars'])==1
    assert replay['bars']==full['bars'][:1] or replay['bars'][0]['close']==full['bars'][0]['close']
    assert not replay['continuous']['gaps']
    assert all('overlap' not in r for r in replay['continuous']['rolls'])
    assert all(b['retrospective'] is False and b['adjustment_offset']==0 for b in replay['bars'])
    for kwargs in ({'cursor':1},{'as_of':datetime(2026,3,16,13,31,tzinfo=UTC)}):
        with pytest.raises(DataError,match='Retrospective'):
            store.snapshot('NQ1! Adjusted',date(2026,3,16),**kwargs)
    with pytest.raises(DataError,match='one selected session'):
        store.snapshot('NQ1! Raw',date(2026,3,16),cursor=1,history_sessions=2)


def test_range_indicators_and_eligibility(artifacts):
    store=artifacts[-1]
    raw=store.snapshot('NQ1! Raw',date(2026,3,16),'daily',history_sessions=2)
    adj=store.snapshot('NQ1! Adjusted',date(2026,3,16),'daily',history_sessions=2)
    assert len(raw['bars'])==2
    assert len(raw['continuous']['rolls'])==1
    assert raw['bars'][0]['source_contract']!=raw['bars'][1]['source_contract']
    assert raw['bars'][1]['eligible_full_session'] is False
    assert raw['continuous']['gap_count']==1
    assert adj['bars'][0]['vwap']==pytest.approx(raw['bars'][0]['vwap']+10)
    assert adj['bars'][1]['vwap']==raw['bars'][1]['vwap']
    assert store.snapshot('NQ1! Raw',date(2026,3,16),cursor=0)['bars']==[]


def test_api_and_strategy_boundary(artifacts,monkeypatch,tmp_path):
    from terminal.api import app,store,continuous_store
    from terminal.research_api import ReleaseWorkspace
    _,_,_,output,_,original,_=artifacts
    monkeypatch.setenv('NQ_CONTINUOUS_ROOT',str(output))
    app.dependency_overrides[store]=lambda:original
    try:
        with TestClient(app) as client:
            assert any(c['contract']=='NQ1! Raw' for c in client.get('/api/contracts').json())
            params={'contract':'NQ1! Raw','session':'2026-03-16','timeframe':'daily','history_sessions':2}
            response=client.get('/api/snapshot',params=params)
            assert response.status_code==200,response.text
            result=response.json()
            assert len(result['bars'])==2
            params.update(contract='NQ1! Adjusted',cursor=1,history_sessions=1)
            assert client.get('/api/snapshot',params=params).status_code==422
            assert client.get('/api/continuous/manifest').json()['quality']['rolls']==1
            assert len(client.get('/api/continuous/gaps',params={'start':'2026-03-13','end':'2026-03-16'}).json())==1
            assert len(client.get('/api/sessions',params={'contract':'NQ1! Raw'}).json())==2
    finally:
        app.dependency_overrides.clear();continuous_store.cache_clear()
    w=ReleaseWorkspace(tmp_path)
    try:
        with pytest.raises(ValueError,match='not executable'):
            w.execute({'contract':'NQ1! Adjusted'})
    finally:w.close()


def test_intraday_windows_are_bounded_retrospective_and_preserve_unresolved_roll(tmp_path, monkeypatch):
    from terminal.api import app

    release, cleaned = make_inputs(tmp_path, missing=True, extended=True)
    output = tmp_path / 'derived'
    build(release, cleaned, output)
    monkeypatch.setenv('NQ_DATA_ROOT', str(release))
    monkeypatch.setenv('NQ_CONTINUOUS_ROOT', str(output))
    params = dict(contract='NQ1! Raw', anchor='2026-03-13', direction='newer', limit=1)
    path = '/api/continuous/intraday'
    with TestClient(app) as client:
        response = client.get(path, params=params)
        assert response.status_code == 200, response.text
        raw = response.json()
        assert raw['session_dates'] == ['2026-03-16']
        assert not raw['at_edge']
        assert raw['rolls'][0]['overlap']['status'] == 'unresolved'
        assert {b['source_contract'] for b in raw['bars']} == {'NQM26'}
        assert {b['adjustment_offset'] for b in raw['bars']} == {0}
        assert all(b['retrospective'] is False for b in raw['bars'])
        gap = datetime.fromisoformat(raw['gaps'][0]['start_utc']).timestamp()
        assert gap not in {b['time'] for b in raw['bars']}
        assert len(raw['bars']) == len({b['time'] for b in raw['bars']}) == 179

        adjusted = client.get(path, params=params | {'contract': 'NQ1! Adjusted'}).json()
        assert adjusted['rolls'] == raw['rolls']
        assert all(b['retrospective'] is True for b in adjusted['bars'])
        earlier = client.get(path, params=params | {'contract': 'NQ1! Adjusted',
                             'anchor': '2026-03-16', 'direction': 'older'}).json()
        assert {b['adjustment_block_id'] for b in earlier['bars']}.isdisjoint(
            b['adjustment_block_id'] for b in adjusted['bars'])

        empty_session = client.get(path, params=params | {'anchor': '2026-03-17'}).json()
        assert empty_session['session_dates'] == ['2026-03-18']
        assert empty_session['bars'] == [] and not empty_session['at_edge']
        latest = client.get(path, params=params | {'anchor': '2026-03-18', 'limit': 2}).json()
        assert latest['session_dates'] == ['2026-03-19'] and latest['at_edge']
        edge = client.get(path, params=params | {'anchor': '2026-03-12', 'direction': 'older'}).json()
        assert edge['session_dates'] == [] and edge['at_edge']

        for invalid in ({'cursor': 0}, {'as_of': '2026-03-16T13:31:00Z'},
                        {'timeframe': 'daily'}, {'limit': 21}, {'contract': 'NQM26'}):
            assert client.get(path, params=params | invalid).status_code == 422
