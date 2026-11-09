"""Read-only, bounded auction statistics endpoints."""
from contextlib import contextmanager
from datetime import date, datetime
from fractions import Fraction
from typing import Annotated, Literal

from duckdb import IOException
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from terminal.api import chart_store, store
from terminal.data import DataError

from .model import session_bounds
from .profile import make_profile
from .source import ObservationSource, Scope, scope_dates

router = APIRouter(prefix='/api/amt', tags=['auction market theory'])


class Request(BaseModel):
    model_config = {'extra': 'forbid'}

    contract: str = Query(pattern=r'^NQ(?:[HMUZ][0-9]{1,2}|1! (?:Raw|Adjusted))$')
    session: date
    display: Literal['Globex', 'RTH'] = 'Globex'
    scope: Scope = 'session'
    start: date | None = None
    end: date | None = None
    as_of: datetime | None = None
    replay: bool = False


class ProfileRequest(Request):
    method: Literal['hlc3', 'uniform'] = 'hlc3'
    row_ticks: int = Query(1, ge=1, le=64)
    value_fraction: float = Query(.70, gt=0, le=1)
    smooth_radius: int = Query(1, ge=0, le=16)
    prominence: float = Query(.01, ge=0, le=1)
    sensitivity: bool = False


def check_stores(db, selected):
    try:
        db.check_seal()
        if selected is not db:
            selected.check_seal()
    except (OSError, DataError) as exc:
        raise HTTPException(503, 'AMT artifacts changed after verification; restart with an intact release') from exc


@contextmanager
def reading(db, request):
    if any(day is not None and not 1900 <= day.year <= 2200
           for day in (request.session, request.start, request.end)):
        raise HTTPException(422, 'AMT trading dates must be between 1900 and 2200')
    if request.contract == 'NQ1! Adjusted' and (request.as_of is not None or request.replay):
        raise HTTPException(422, 'Retrospective adjusted prices are unavailable in replay/as_of')
    selected = chart_store(db, request.contract)
    check_stores(db, selected)
    try:
        source = ObservationSource(db, selected, request.contract, request.display, request.as_of, request.replay)
        yield source
    except DataError as exc:
        check_stores(db, selected)
        raise HTTPException(422, str(exc)) from exc
    except (OSError, IOException) as exc:
        raise HTTPException(503, 'AMT artifacts are unavailable; restart with an intact release') from exc
    check_stores(db, selected)


def load_scope(source, request, options):
    first, last = scope_dates(request.scope, request.session, request.start, request.end)
    if request.scope == 'prior_session':
        prior = source.prior(request.session)
        if prior is None:
            raise DataError('No prior candidate session in this scope')
        first = last = prior
    cutoff = source.as_of or session_bounds(last, request.display)[1]
    samples = source.load(first, last, cutoff)
    if request.scope == 'prior_session' and not (samples and samples[0].coverage['complete']):
        raise DataError('Prior candidate session is unavailable or incomplete in this display')
    return samples, source.envelope(request.scope, first, last, cutoff, samples, options)


@router.get('/profile')
def profile(request: Annotated[ProfileRequest, Query()], db=Depends(store)):
    options = request.model_dump(exclude=set(Request.model_fields))
    with reading(db, request) as source:
        samples, envelope = load_scope(source, request, options)
        bars = [bar for sample in samples for bar in sample.bars]
        return dict(envelope, profile=make_profile(bars, request.method, request.row_ticks,
                    Fraction(str(request.value_fraction)), request.smooth_radius, request.prominence,
                    request.sensitivity))


class TpoRequest(Request):
    row_ticks: int = Query(1, ge=1, le=64)
    period_minutes: int = Query(30, ge=5, le=120)
    ib_minutes: int = Query(60, ge=1, le=120)
    value_fraction: float = Query(.70, gt=0, le=1)
    representation: Literal['none', 'blocks', 'letters'] = 'none'


@router.get('/tpo')
def tpo(request: Annotated[TpoRequest, Query()], db=Depends(store)):
    from .tpo import make_tpo

    options = request.model_dump(exclude=set(Request.model_fields))
    with reading(db, request) as source:
        samples, envelope = load_scope(source, request, options)
        return dict(envelope, tpo=make_tpo(samples, envelope['cutoff']['as_of'], request.display,
                    request.row_ticks, request.period_minutes, Fraction(str(request.value_fraction)),
                    request.representation, request.ib_minutes))
