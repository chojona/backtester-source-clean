"""Bounded local API. No write, brokerage, or certification endpoints."""
from __future__ import annotations

import os
from datetime import date, datetime
from functools import lru_cache
from typing import Annotated, Literal

from duckdb import IOException
from fastapi import Depends, FastAPI, HTTPException, Query

from .chart_window import chart_window, series_identity
from .data import DataError, ResearchStore

app = FastAPI(title='NQ Quant Research Terminal', version='0.3.0')
Frame = Literal['1m', '5m', '15m', '30m', '1h', 'daily']
Contract = Annotated[str, Query(pattern=r'^NQ(?:[HMUZ][0-9]{1,2}|1! (?:Raw|Adjusted))$')]


@lru_cache(maxsize=1)
def store():
    root = os.environ.get('NQ_DATA_ROOT')
    if not root:
        raise HTTPException(503, 'Set NQ_DATA_ROOT to the sealed v2.0.0 build directory; no sample data is substituted.')
    try:
        return ResearchStore(root)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, f'Dataset unavailable or invalid: {exc}') from exc


def chart_store(db, contract):
    if contract not in ('NQ1! Raw', 'NQ1! Adjusted'):
        return db
    root = os.getenv('NQ_CONTINUOUS_ROOT')
    if not root:
        raise HTTPException(503, 'Build continuous artifacts and configure NQ_CONTINUOUS_ROOT')
    try:
        return continuous_store(root, db)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, f'Continuous dataset unavailable: {exc}') from exc


@lru_cache(maxsize=1)
def continuous_store(root, db):
    from .continuous_data import ContinuousStore
    return ContinuousStore(root, db)


@app.get('/api/health')
def health(db=Depends(store)):
    return {'status': 'ready', 'version': db.summary['version']}


@app.get('/api/provenance')
def provenance(db=Depends(store)):
    result = db.provenance()
    result['chart_series'] = series_identity(db, db)
    if os.getenv('NQ_CONTINUOUS_ROOT'):
        continuous = chart_store(db, 'NQ1! Raw')
        result['continuous'] = {'build_id':continuous.manifest['build_id'], 'quality':continuous.quality,
                                'policy':continuous.manifest['specification'],
                                'chart_series':series_identity(db, continuous)}
    return result


@app.get('/api/contracts')
def contracts(db=Depends(store)):
    return db.contracts() + (chart_store(db,'NQ1! Raw').contracts() if os.getenv('NQ_CONTINUOUS_ROOT') else [])


@app.get('/api/sessions')
def sessions(contract: Contract | None = None, start: date | None = None, end: date | None = None,
             limit: int = Query(2000, ge=1, le=5000), offset: int = Query(0, ge=0), db=Depends(store)):
    if start and end and start > end:
        raise HTTPException(422, 'start must not follow end')
    return chart_store(db, contract).sessions(contract, start, end, limit, offset)


def session_snapshot(contract: Contract, session: date, timeframe: Frame = '1m',
                     cursor: int | None = Query(None, ge=0, le=1500), as_of: datetime | None = None,
                     offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
                     display: Literal['Globex', 'RTH'] = 'Globex',
                     opening_minutes: int = Query(30, ge=1, le=120), deviations: float = Query(1, ge=.25, le=5),
                     history_sessions: int = Query(1,ge=1,le=5000), db=Depends(store)):
    try:
        selected = chart_store(db,contract)
        if selected is not db:
            return selected.snapshot(contract,session,timeframe,cursor,as_of,offset,limit,display,opening_minutes,deviations,history_sessions)
        if history_sessions != 1:
            raise DataError('Multi-session history requires a continuous symbol')
        return db.snapshot(contract, session, timeframe, cursor, as_of, offset, limit, display, opening_minutes, deviations)
    except DataError as exc:
        raise HTTPException(422, str(exc)) from exc


app.get('/api/snapshot')(session_snapshot)


@app.get('/api/chart/window')
def historical_chart_window(
    contract: Contract, timeframe: Frame = '1m', display: Literal['Globex', 'RTH'] = 'Globex',
    opening_minutes: int = Query(30, ge=1, le=120), deviations: float = Query(1, ge=.25, le=5),
    session: date | None = None, cursor: str | None = Query(None, max_length=256),
    as_of: datetime | None = None, sessions: int = Query(20, ge=1, le=250),
    start_sessions: int | None = Query(None, ge=1, le=250), db=Depends(store),
):
    selected = chart_store(db, contract)
    def check_artifacts():
        db.check_seal()
        if selected is not db:
            selected.check_seal()

    try:
        check_artifacts()
        try:
            page = chart_window(db, selected, contract, timeframe, display, opening_minutes, deviations,
                                as_of, session, cursor, sessions, start_sessions)
        except DataError as exc:
            raise HTTPException(422, str(exc)) from exc
        check_artifacts()
        return page
    except (OSError, IOException, DataError) as exc:
        raise HTTPException(503, 'Chart artifacts changed after verification; restart with an intact release') from exc


@app.get('/api/statistics')
def statistics(snapshot=Depends(session_snapshot)):
    return {'as_of': snapshot['as_of'], 'stats': snapshot['stats'], 'previous': snapshot['previous']}


@app.get('/api/indicators')
def indicators(snapshot=Depends(session_snapshot)):
    return {'as_of': snapshot['as_of'], 'previous': snapshot['previous'], 'points': [
        {k: b[k] for k in ('time', 'vwap', 'vwap_upper', 'vwap_lower', 'or_high', 'or_low', 'available_at')} for b in snapshot['bars']]}


@app.get('/api/bars')
def bars(contract: Contract, start: date, end: date, timeframe: Frame = '1m',
         as_of: datetime | None = None, db=Depends(store)):
    if not 0 <= (end - start).days <= 31:
        raise HTTPException(422, 'Range must be ordered and at most 31 days (inclusive)')
    if as_of and as_of.tzinfo is None:
        raise HTTPException(422, 'as_of must include a timezone')
    db = chart_store(db,contract)
    if contract == "NQ1! Adjusted" and as_of is not None:
        raise HTTPException(422,"Retrospective adjusted prices are unavailable in replay/as_of")
    sessions = db.sessions(contract, start, end, 32, 0)
    # Each session stays separate. Session VWAP resets and daily candles never cross contracts.
    return {'contract': contract, 'sessions': [
        {'session': s['trading_date'], 'bars': db.snapshot(contract, date.fromisoformat(s['trading_date']),
            timeframe, as_of=as_of)['bars']} for s in reversed(sessions)]}


@app.get('/api/rolls')
def rolls(contract: Contract, db=Depends(store)):
    if contract.startswith('NQ1!'):
        return chart_store(db,contract).rolls
    return db.query('''SELECT trading_date, selected_contract, legacy_contract, quality_flags
                       FROM rolls WHERE selected_contract=? ORDER BY trading_date''', [contract])


@app.get('/api/replay-time')
def replay_time(contract: Contract, session: date, time: Annotated[str, Query(pattern=r'^\d{2}:\d{2}$')], db=Depends(store)):
    try:
        return {'cursor': chart_store(db,contract).cursor_at(contract, session, time)}
    except DataError as exc:
        raise HTTPException(422, str(exc)) from exc


from .research_api import router as research_router
app.include_router(research_router)


@app.get('/api/continuous/manifest')
def continuous_manifest(db=Depends(store)):
    continuous=chart_store(db,'NQ1! Raw')
    return {'manifest':continuous.manifest,'rolls':continuous.rolls,'quality':continuous.quality}


@app.get('/api/continuous/intraday')
def continuous_intraday(
    contract: Literal['NQ1! Raw', 'NQ1! Adjusted'],
    anchor: date,
    direction: Literal['older', 'newer'],
    timeframe: Literal['1m', '5m', '15m', '30m', '1h'] = '1m',
    display: Literal['Globex', 'RTH'] = 'Globex',
    opening_minutes: int = Query(30, ge=1, le=120),
    deviations: float = Query(1, ge=.25, le=5),
    limit: int = Query(10, ge=1, le=20),
    cursor: int | None = None,
    as_of: datetime | None = None,
    db=Depends(store),
):
    if cursor is not None or as_of is not None:
        raise HTTPException(422, 'Intraday history windows are for retrospective browsing only')
    try:
        return chart_store(db, contract).intraday_window(
            contract, anchor, direction, timeframe, display, opening_minutes, deviations, limit,
        )
    except DataError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get('/api/continuous/gaps')
def continuous_gaps(start:date,end:date,as_of:datetime|None=None,
                    limit:int=Query(500,ge=1,le=2000),offset:int=Query(0,ge=0),db=Depends(store)):
    if start>end or as_of is not None and as_of.tzinfo is None:
        raise HTTPException(422,'Ordered date range and aware cutoff required')
    from datetime import timezone
    cutoff=as_of or datetime.max.replace(tzinfo=timezone.utc)
    continuous=chart_store(db,'NQ1! Raw')
    return continuous.query('NQ1! Raw','''SELECT * FROM gaps WHERE trading_date>=? AND trading_date<=?
        AND CAST(end_exclusive_utc AS TIMESTAMPTZ)<=? ORDER BY start_utc LIMIT ? OFFSET ?''',
        [start.isoformat(),end.isoformat(),cutoff,limit,offset])


from .amt.api import router as amt_router
app.include_router(amt_router)
