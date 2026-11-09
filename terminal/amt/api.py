"""Read-only, bounded auction statistics endpoints."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from fractions import Fraction
import re
from typing import Annotated, Literal

from duckdb import IOException
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, BeforeValidator

from terminal.data import DataError
from terminal.stores import CONTRACT_PATTERN, chart_store, store

from .context import profile_context
from .model import MAX_OBSERVATIONS, MAX_PRICE_ROWS, TICK_SIZE, VERSION, session_bounds, trading_date
from .profile import METHODS, VOLUME_SCALE, make_profile, value_area, weights
from .source import ObservationSource, Scope, scope_dates
from .tpo import make_tpo
from .vwap import make_vwap

router = APIRouter(prefix='/api/amt', tags=['auction market theory'])


def calendar_date(value):
    if isinstance(value, str) and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Use an ISO trading date (YYYY-MM-DD)')
    return value


def iso_timestamp(value):
    if isinstance(value, str) and not re.match(r'^\d{4}-\d{2}-\d{2}[Tt ]', value):
        raise ValueError('Use an ISO timestamp with a timezone')
    return value


CalendarDate = Annotated[date, BeforeValidator(calendar_date)]
ObservationTime = Annotated[datetime, BeforeValidator(iso_timestamp)]


class Request(BaseModel):
    model_config = {'extra': 'forbid'}

    contract: str = Query(pattern=CONTRACT_PATTERN)
    session: CalendarDate
    display: Literal['Globex', 'RTH'] = 'Globex'
    scope: Scope = 'session'
    start: CalendarDate | None = None
    end: CalendarDate | None = None
    as_of: ObservationTime | None = None
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
    options = request.model_dump(exclude=set(Request.model_fields))
    with reading(db, request) as source:
        samples, envelope = load_scope(source, request, options)
        return dict(envelope, tpo=make_tpo(samples, envelope['cutoff']['as_of'], request.display,
                    request.row_ticks, request.period_minutes, Fraction(str(request.value_fraction)),
                    request.representation, request.ib_minutes))


class VwapRequest(Request):
    scope: Literal['session', 'week', 'prior_week', 'month', 'prior_month', 'manual'] = 'session'
    anchor: ObservationTime | None = None
    points_from: ObservationTime | None = None
    deviations: float = Query(1, ge=.25, le=5)


@router.get('/vwap')
def vwap(request: Annotated[VwapRequest, Query()], db=Depends(store)):
    with reading(db, request) as source:
        anchor, points_from = request.anchor, request.points_from
        if (request.scope == 'manual') != (anchor is not None):
            raise DataError('A manual VWAP requires an anchor; other VWAP scopes do not take one')
        for stamp in (anchor, points_from):
            if stamp is not None and (stamp.utcoffset() is None or not 1900 <= stamp.year <= 2200):
                raise DataError('VWAP timestamps must include a timezone and a supported date')
        anchor = anchor.astimezone(timezone.utc) if anchor else None
        points_from = points_from.astimezone(timezone.utc) if points_from else None
        options = {'anchor': anchor.isoformat() if anchor else None,
                   'points_from': points_from.isoformat() if points_from else None,
                   'deviations': request.deviations}
        if anchor is not None:
            first, last = scope_dates('range', request.session, trading_date(anchor), request.session)
            if request.start is not None or request.end is not None:
                raise DataError('Manual scope is bounded by anchor and session')
            cutoff = source.as_of or session_bounds(last, request.display)[1]
            if anchor > min(cutoff, session_bounds(last, request.display)[1]):
                raise DataError('VWAP anchor is beyond the selected observation scope')
            samples = source.load(first, last, cutoff, starts_at=anchor)
            envelope = source.envelope('manual', first, last, cutoff, samples, options)
        else:
            samples, envelope = load_scope(source, request, options)
        return dict(envelope, vwap=make_vwap(samples, anchor, envelope['cutoff']['as_of'],
                                            request.deviations, points_from))


class ContextRequest(Request):
    method: Literal['hlc3', 'uniform'] = 'hlc3'
    row_ticks: int = Query(1, ge=1, le=64)
    value_fraction: float = Query(.70, gt=0, le=1)
    ib_minutes: int = Query(60, ge=1, le=120)


def previous_value(source, first, scope, cutoff, coordinate, options, fraction):
    if scope in ('week', 'prior_week', 'month', 'prior_month'):
        kind = 'prior_week' if 'week' in scope else 'prior_month'
        start, end = scope_dates(kind, first, None, None)
    else:
        kind = 'prior_session'
        start = end = source.prior(first)
        if start is None:
            return {'status': 'no_prior_candidate', 'value': None}
    if coordinate is None:
        return {'status': 'current_coordinate_unavailable', 'value': None}
    prior_cutoff = min(cutoff, session_bounds(end, source.display)[1])
    samples = source.load(start, end, prior_cutoff)
    # An incomplete or foreign prior is reported without publishing its price levels.
    if not samples or not all(s.coverage['complete'] for s in samples):
        return {'status': 'prior_incomplete_or_excluded', 'value': None, 'start': start, 'end': end}
    try:
        compatible = source.coordinate(samples) == coordinate
    except DataError:
        compatible = False
    if not compatible:
        return {'status': 'incompatible_price_coordinate', 'value': None, 'start': start, 'end': end}
    prior = source.envelope(kind, start, end, prior_cutoff, samples, options)
    rows = weights((bar for sample in samples for bar in sample.bars), options['method'], options['row_ticks'])
    value = value_area(rows, options['row_ticks'], fraction)
    return dict(prior, status='available' if value else 'zero_volume', value=value)


@router.get('/context')
def context(request: Annotated[ContextRequest, Query()], db=Depends(store)):
    options = request.model_dump(exclude=set(Request.model_fields))
    fraction = Fraction(str(request.value_fraction))
    with reading(db, request) as source:
        samples, envelope = load_scope(source, request, options)
        cutoff = envelope['cutoff']['as_of']
        rows = weights((bar for sample in samples for bar in sample.bars), request.method, request.row_ticks)
        area = value_area(rows, request.row_ticks, fraction)
        previous = previous_value(source, envelope['start'], request.scope, cutoff,
                                  envelope['source']['coordinate'], options, fraction)
        return dict(envelope, classification=f'ohlcv_{request.method}_auction_context_estimate',
                    previous=previous, context=profile_context(samples, cutoff, area,
                                                                previous['value'], request.ib_minutes))


@router.get('/capabilities')
def capabilities():
    return {'methodology_version': VERSION, 'input': 'sealed one-minute NQ OHLCV',
            'tick_size': TICK_SIZE, 'volume_scale': VOLUME_SCALE,
            'profile_methods': METHODS, 'tpo_classification': 'ohlcv_bar_range_tpo_estimate',
            'vwap_classification': 'ohlcv_hlc3_weighted_vwap_estimate',
            'scopes': ['session', 'prior_session', 'range', 'week', 'prior_week', 'month', 'prior_month'],
            'vwap_scopes': ['session', 'manual', 'week', 'prior_week', 'month', 'prior_month'],
            'limits': {'calendar_days': 31, 'observations': MAX_OBSERVATIONS, 'price_rows': MAX_PRICE_ROWS},
            'replay': {'exact': True, 'raw': True, 'adjusted': False, 'basis': 'observation_close',
                       'historical_publication_verified': False, 'retrospective_eligibility': True},
            'trade_exact': False, 'strict_eligible': False, 'execution_eligible': False}
