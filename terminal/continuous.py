"""Offline, reproducible continuous-chart artifacts. Source files are read-only.

python -m terminal.continuous --release /external/v2/build \
  --cleaned /external/cleaned --output /external/nq-continuous-v1
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from zoneinfo import ZoneInfo

import duckdb
from .data import digest, DataError

VERSION = 'nq-continuous-v1.0.0'
POLICY_VERSION = 'nq-v2-fixed-monday-v1'
SELECTION = 'Fixed Monday before nominal third Friday; switch at session open. Custom retrospective calendar policy for all years, not a claim of historical official lead designation.'
SYMBOLS = {'NQ1! Raw': 'raw.parquet', 'NQ1! Adjusted': 'adjusted.parquet'}
NY = ZoneInfo('America/New_York')
UTC = timezone.utc
CONVENTION = {
    'version': 'prior-overlap-close-v1', 'lookback_calendar_days': 7,
    'minimum_consecutive_pairs': 5,
    'reference': 'Latest synchronous positive-volume one-minute close strictly before roll session open; require preceding four consecutive paired minutes.',
    'gap': 'new reference close minus old reference close; one exact timestamp on both contracts',
    'backward': 'Newest segment offset zero; earlier offset = next offset + next roll gap. An unresolved roll makes every earlier offset null.',
    'missing': 'Unresolved links split independently anchored blocks. Each block newest segment has offset zero; no cross-block gap is assumed. Global latest-anchor offsets remain null before unresolved links.',
    'availability': 'OHLCV close-time assumption; no independent historical publication evidence',
}


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identity(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def iso(value):
    return value.astimezone(UTC).isoformat()


def choose(day):
    """Frozen exact v2 rule (expansion.choose), independent of market records."""
    for year in (day.year, day.year + 1):
        for month, code in [(3, 'H'), (6, 'M'), (9, 'U'), (12, 'Z')]:
            first = date(year, month, 1)
            friday = first + timedelta(days=(4 - first.weekday()) % 7 + 14)
            if day < friday - timedelta(days=4):
                return f'NQ{code}{year % 100:02d}'
    raise DataError('Cannot select contract')


def roll_open(day):
    # Every v2 quarterly transition is a Monday. Its ordinary session opens
    # Sunday 18:00 ET in all retained historical ordinary-hour regimes.
    if day.weekday() != 0:
        raise DataError('v2 quarterly transition must be a Monday')
    return datetime.combine(day - timedelta(days=1), datetime.min.time(), NY).replace(hour=18).astimezone(UTC)


def offsets(gaps):
    values = [0.0] * (len(gaps) + 1)
    for i in range(len(gaps) - 1, -1, -1):
        values[i] = None if gaps[i] is None or values[i + 1] is None else values[i + 1] + gaps[i]
    return values


def block_offsets(gaps):
    values=[0.0]*(len(gaps)+1)
    blocks=[sum(gap is None for gap in gaps)]*(len(gaps)+1)
    for i in range(len(gaps)-1,-1,-1):
        if gaps[i] is None:
            values[i]=0.0
            blocks[i]=blocks[i+1]-1
        else:
            values[i]=values[i+1]+gaps[i]
            blocks[i]=blocks[i+1]
    return values,blocks


def overlap_evidence(rows, decision):
    """rows: descending (timestamp, old close, new close, old vol, new vol)."""
    if len(rows) < 5:
        return {'status': 'unresolved', 'gap': None, 'reason': 'fewer than five synchronous positive-volume observations'}
    rows = rows[:5]
    if any(not decision - timedelta(days=7) <= r[0] or r[0] + timedelta(minutes=1) >= decision for r in rows):
        return {'status': 'unresolved', 'gap': None, 'reason': 'overlap outside strict predecision window'}
    if any(rows[i][0] - rows[i+1][0] != timedelta(minutes=1) for i in range(4)):
        return {'status': 'unresolved', 'gap': None, 'reason': 'latest five paired observations are not consecutive'}
    if any(not all(math.isfinite(float(v)) and v > 0 for v in r[1:]) for r in rows):
        return {'status': 'unresolved', 'gap': None, 'reason': 'nonpositive or nonfinite reference data'}
    latest = rows[0]
    return {'status': 'supported_observed_overlap', 'gap': latest[2] - latest[1],
            'reference_bar_open_utc': iso(latest[0]), 'reference_bar_close_utc': iso(latest[0]+timedelta(minutes=1)),
            'old_close': latest[1], 'new_close': latest[2], 'paired_observations': len(rows),
            'evidence_sha256': identity([[iso(r[0]), *r[1:]] for r in rows]),
            'pairs': [[iso(r[0]), *r[1:]] for r in rows]}


def verify_release(release, cleaned):
    seal = json.loads((release/'SUCCESS.json').read_text())
    if seal['version'] != 'nq-ohlcv-research-v2.0.0':
        raise DataError('Expected v2.0.0 release')
    names = ['selected-observations-with-flags.parquet', 'session-eligibility.parquet',
             'contract-rolls.parquet', 'selected-gap-intervals.parquet', 'summary.json', 'input-bindings.json']
    hashes = {}
    for name in names:
        hashes[name] = digest(release/name)
        if hashes[name] != seal['outputs'][name]:
            raise DataError('Changed release artifact: '+name)
    summary = json.loads((release/'summary.json').read_text())
    if summary['policy']['selection'] != SELECTION:
        raise DataError('Selection policy changed; refusing silent policy migration')
    bindings = json.loads((release/'input-bindings.json').read_text())
    for name in ['nq-ohlcv-1m.parquet', 'SUCCESS.json']:
        path = (cleaned/name).resolve()
        expected = bindings.get(str(path))
        actual = digest(path)
        if expected != actual:
            raise DataError('Cleaned source not bound to v2 release: '+name)
        hashes['cleaned/'+name] = actual
    return summary, hashes


def build(release, cleaned, output):
    release, cleaned, output = (Path(p).expanduser().resolve() for p in (release, cleaned, output))
    repo = Path(__file__).resolve().parents[1]
    if output == repo or repo in output.parents or output in (release, cleaned) or release in output.parents or cleaned in output.parents:
        raise DataError('Derived market artifacts must live outside the source repository and original datasets')
    summary, hashes = verify_release(release, cleaned)
    specification = {'version': VERSION, 'policy_version': POLICY_VERSION, 'selection': SELECTION,
        'policy_adopted_retrospectively': True, 'decision_inputs': 'calendar dates only; no volume, OI or future market observations',
        'adjustment': CONVENTION, 'inputs': hashes, 'code_sha256': digest(Path(__file__)),
        'dataset_version': summary['version'], 'strict_eligible': False, 'performance_eligible': False,
        'runtime': {'duckdb': duckdb.__version__}}
    build_id = identity(specification)
    if output.exists():
        manifest = json.loads((output/'SUCCESS.json').read_text())
        if manifest['build_id'] != build_id:
            raise DataError('Output exists for a different build; choose a new version directory')
        for name, expected in manifest['outputs'].items():
            if digest(output/name) != expected:
                raise DataError('Existing continuous artifact changed: '+name)
        return manifest
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.nq-continuous-', dir=output.parent))
    try:
        with duckdb.connect(':memory:') as con:
            con.execute("SET TimeZone='UTC'")
            con.execute('SET threads=1')
            for view, path in [('selected', release/'selected-observations-with-flags.parquet'),
                               ('sessions', release/'session-eligibility.parquet'), ('rolls', release/'contract-rolls.parquet'),
                               ('clean', cleaned/'nq-ohlcv-1m.parquet')]:
                con.execute(f'CREATE VIEW {view} AS SELECT * FROM read_parquet({literal(path)})')
            session_rows = con.execute('SELECT trading_date,selected_contract,roll FROM sessions ORDER BY trading_date').fetchall()
            if len({r[0] for r in session_rows}) != len(session_rows) or not session_rows:
                raise DataError('Duplicate or empty session manifest')
            transitions, segment_rows = [], []
            current, segment = None, -1
            for daystr, contract, flagged in session_rows:
                day = date.fromisoformat(daystr)
                if choose(day) != contract:
                    raise DataError('Manifest disagrees with frozen calendar selection: '+daystr)
                change = current is not None and current != contract
                if bool(flagged) != change:
                    raise DataError('Roll flag disagrees with chronological selection')
                if current != contract:
                    segment += 1
                    if change:
                        decision = roll_open(day)
                        roll_id = f'{daystr}:{current}:{contract}'
                        candidates = con.execute('''SELECT a.timestamp_utc,a.close,b.close,a.volume,b.volume
                          FROM clean a JOIN clean b USING(timestamp_utc)
                          WHERE a.contract=? AND b.contract=? AND a.volume>0 AND b.volume>0
                          AND CAST(a.timestamp_utc AS TIMESTAMPTZ)>=? AND CAST(a.timestamp_utc AS TIMESTAMPTZ) + INTERVAL 1 MINUTE<?
                          ORDER BY a.timestamp_utc DESC LIMIT 5''',
                          [current,contract,decision-timedelta(days=7),decision]).fetchall()
                        evidence = overlap_evidence(candidates,decision)
                        transitions.append({'roll_id': roll_id, 'trading_date':daystr,
                            'decision_utc':iso(decision), 'old_contract':current,'new_contract':contract,
                            'policy_version':POLICY_VERSION,'segment_id':segment,'overlap':evidence})
                    current = contract
                segment_rows.append((daystr,contract,segment,transitions[-1]['roll_id'] if transitions else 'initial'))
            expected_rolls = con.execute('SELECT trading_date,selected_contract FROM rolls ORDER BY trading_date').fetchall()
            if expected_rolls != [(r['trading_date'],r['new_contract']) for r in transitions] or len(transitions) != summary['rolls']:
                raise DataError('Roll manifest mismatch')
            n = con.execute('SELECT count(*) FROM selected').fetchone()[0]
            if con.execute('SELECT count(*) FROM (SELECT timestamp_utc FROM selected GROUP BY ALL HAVING count(*)>1)').fetchone()[0]:
                raise DataError('Duplicate selected timestamp')
            if con.execute('''SELECT count(*) FROM selected s LEFT JOIN clean c USING(timestamp_utc,contract)
                WHERE c.contract IS NULL OR s.contract!=s.selected_contract OR
                s.open IS DISTINCT FROM c.open OR s.high IS DISTINCT FROM c.high OR
                s.low IS DISTINCT FROM c.low OR s.close IS DISTINCT FROM c.close OR s.volume IS DISTINCT FROM c.volume''').fetchone()[0]:
                raise DataError('Source observations do not reconcile with cleaned outright data')
            con.execute('CREATE TABLE mapping(trading_date VARCHAR,source_contract VARCHAR,segment_id INTEGER,roll_id VARCHAR)')
            con.executemany('INSERT INTO mapping VALUES (?,?,?,?)',segment_rows)
            adjustment = offsets([r['overlap']['gap'] for r in transitions])
            local_offsets,blocks=block_offsets([r['overlap']['gap'] for r in transitions])
            con.execute('CREATE TABLE adjustments(segment_id INTEGER,backward_offset DOUBLE,global_offset DOUBLE,adjustment_block_id INTEGER)')
            con.executemany('INSERT INTO adjustments VALUES (?,?,?,?)',[(i,local_offsets[i],v,blocks[i]) for i,v in enumerate(adjustment)])
            con.execute('''CREATE TEMP TABLE base AS SELECT s.*,m.segment_id,m.roll_id,
                a.backward_offset,a.global_offset,a.adjustment_block_id, false AS strict_eligible, false AS performance_eligible,
                s.contract AS source_contract,
                s.open AS raw_open,s.high AS raw_high,s.low AS raw_low,s.close AS raw_close
                FROM selected s JOIN mapping m ON s.trading_date=m.trading_date AND s.contract=m.source_contract
                JOIN adjustments a USING(segment_id) ORDER BY timestamp_utc''')
            if con.execute('SELECT count(*) FROM base').fetchone()[0] != n:
                raise DataError('Session-to-source reconciliation lost observations')
            # Same-contract, same-session, eligible, consecutive observations only.
            con.execute('''CREATE TEMP VIEW return_base AS SELECT *,
                CASE WHEN eligible_full_session AND lag(eligible_full_session) OVER w
                AND source_contract=lag(source_contract) OVER w AND trading_date=lag(trading_date) OVER w
                AND CAST(timestamp_utc AS TIMESTAMPTZ)=CAST(lag(timestamp_utc) OVER w AS TIMESTAMPTZ) + INTERVAL 1 MINUTE
                THEN ln(close/lag(close) OVER w) ELSE NULL END AS same_contract_log_return
                FROM base WINDOW w AS (ORDER BY timestamp_utc)''')
            for adjusted, name in [(False,'raw.parquet'),(True,'adjusted.parquet')]:
                prices = ','.join(f'{key}+backward_offset AS {key}' for key in ('open','high','low','close'))
                query = f'''SELECT * EXCLUDE(backward_offset,global_offset{',open,high,low,close' if adjusted else ',adjustment_block_id'}),
                    {prices+',' if adjusted else ''}
                    {'backward_offset' if adjusted else '0.0::DOUBLE'} AS adjustment_offset,
                    {'global_offset AS global_adjustment_offset,' if adjusted else ''}
                    {'true' if adjusted else 'false'} AS retrospective,
                    CASE WHEN {'global_offset IS NULL' if adjusted else 'false'} THEN 'independent_block_unresolved_global_anchor'
                         ELSE {'\'backward_additive\'' if adjusted else '\'unadjusted\''} END AS adjustment_status
                    FROM return_base ORDER BY timestamp_utc'''
                con.execute(f'COPY ({query}) TO {literal(stage/name)} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)')
            for name in ['session-eligibility.parquet','selected-gap-intervals.parquet']:
                shutil.copyfile(release/name,stage/name)
            quality = {'version':VERSION,'observed_bars':n,'sessions':len(session_rows),'rolls':len(transitions),
                'supported_rolls':sum(r['overlap']['gap'] is not None for r in transitions),
                'unresolved_rolls':[r['roll_id'] for r in transitions if r['overlap']['gap'] is None],
                'eligible_bars':con.execute('SELECT count(*) FROM base WHERE eligible_full_session').fetchone()[0],
                'excluded_observed_bars':con.execute('SELECT count(*) FROM base WHERE NOT eligible_full_session').fetchone()[0],
                'unadjustable_to_latest_anchor_bars':con.execute('SELECT count(*) FROM base WHERE global_offset IS NULL').fetchone()[0],
                'independently_anchored_blocks':len(set(blocks)), 'adjustment_across_unresolved_rolls':False,
                'missing_intervals':con.execute(f'SELECT count(*) FROM read_parquet({literal(release/"selected-gap-intervals.parquet")})').fetchone()[0],
                'source_prices_and_volume_preserved':True,'roll_returns_excluded':True,'no_imputation':True,
                'strict_eligible':False,'publication_evidence':'retrospective close-time assumption only',
                'limitations':['Calendar policy is retrospective adoption of a fixed date-only rule.',
                    'Ordinary calendar eligibility is not strict historical certification.',
                    'Adjusted blocks use future rolls; no common price anchor across unresolved roll boundaries; replay and performance disabled.',
                    'Matched overlap prices do not establish official settlement prices or historical publication.']}
            documents = {'rollover-manifest.json':{'version':VERSION,'policy':specification,'rolls':transitions},
                'adjustment-manifest.json':{'version':VERSION,'retrospective':True,'convention':CONVENTION,
                    'segments':[{'segment_id':i,'offset':local_offsets[i],'global_offset':v,'block_id':blocks[i],'status':'supported' if v is not None else 'independent_block_unresolved_global_anchor'} for i,v in enumerate(adjustment)]},
                'quality-report.json':quality}
            for name, value in documents.items():
                (stage/name).write_text(canonical(value)+'\n')
        # Check source byte identities again after the build to detect concurrent changes.
        _, after = verify_release(release,cleaned)
        if after != hashes:
            raise DataError('Source changed during build')
        manifest = {'version':VERSION,'build_id':build_id,'specification':specification,
                    'outputs':{p.name:digest(p) for p in sorted(stage.iterdir())}}
        (stage/'SUCCESS.json').write_text(canonical(manifest)+'\n')
        os.rename(stage,output)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True,type=Path)
    parser.add_argument('--cleaned',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    result=build(args.release,args.cleaned,args.output)
    print(json.dumps({'version':VERSION,'build_id':result['build_id'],'output':str(args.output)},indent=2))


if __name__=='__main__':
    main()
