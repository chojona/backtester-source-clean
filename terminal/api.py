"""Bounded local API. No write, brokerage, or certification endpoints."""
from __future__ import annotations

import os
from datetime import date, datetime
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query

from .data import DataError, ResearchStore

app = FastAPI(title='NQ Quant Research Terminal', version='0.2.0')
Frame = Literal['1m', '5m', '15m', '30m', '1h', 'daily']
Contract = Annotated[str, Query(pattern=r'^NQ[HMUZ][0-9]{1,2}$')]


@lru_cache(maxsize=1)
def store():
    root = os.environ.get('NQ_DATA_ROOT')
    if not root:
        raise HTTPException(503, 'Set NQ_DATA_ROOT to the sealed v2.0.0 build directory; no sample data is substituted.')
    try:
        return ResearchStore(root)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, f'Dataset unavailable or invalid: {exc}') from exc


@app.get('/api/health')
def health(db=Depends(store)):
    return {'status': 'ready', 'version': db.summary['version']}


@app.get('/api/provenance')
def provenance(db=Depends(store)):
    return db.provenance()


@app.get('/api/contracts')
def contracts(db=Depends(store)):
    return db.contracts()


@app.get('/api/sessions')
def sessions(contract: Contract | None = None, start: date | None = None, end: date | None = None,
             limit: int = Query(2000, ge=1, le=2000), offset: int = Query(0, ge=0), db=Depends(store)):
    if start and end and start > end:
        raise HTTPException(422, 'start must not follow end')
    return db.sessions(contract, start, end, limit, offset)


def session_snapshot(contract: Contract, session: date, timeframe: Frame = '1m',
                     cursor: int | None = Query(None, ge=0, le=1500), as_of: datetime | None = None,
                     offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
                     display: Literal['Globex', 'RTH'] = 'Globex',
                     opening_minutes: int = Query(30, ge=1, le=120), deviations: float = Query(1, ge=.25, le=5), db=Depends(store)):
    try:
        return db.snapshot(contract, session, timeframe, cursor, as_of, offset, limit, display, opening_minutes, deviations)
    except DataError as exc:
        raise HTTPException(422, str(exc)) from exc


app.get('/api/snapshot')(session_snapshot)


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
    sessions = db.sessions(contract, start, end, 32, 0)
    # Each session stays separate. Session VWAP resets and daily candles never cross contracts.
    return {'contract': contract, 'sessions': [
        {'session': s['trading_date'], 'bars': db.snapshot(contract, date.fromisoformat(s['trading_date']),
            timeframe, as_of=as_of)['bars']} for s in reversed(sessions)]}


@app.get('/api/rolls')
def rolls(contract: Contract, db=Depends(store)):
    return db.query('''SELECT trading_date, selected_contract, legacy_contract, quality_flags
                       FROM rolls WHERE selected_contract=? ORDER BY trading_date''', [contract])


@app.get('/api/replay-time')
def replay_time(contract: Contract, session: date, time: Annotated[str, Query(pattern=r'^\d{2}:\d{2}$')], db=Depends(store)):
    try:
        return {'cursor': db.cursor_at(contract, session, time)}
    except DataError as exc:
        raise HTTPException(422, str(exc)) from exc
