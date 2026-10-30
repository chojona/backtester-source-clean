"""Deterministic invented provider fixtures. None represent market history."""
import base64
from dataclasses import replace
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
import json,sys,os
import pytest
from backtester.providers.databento import (DownloadRequest,HistoricalGateway,MissingAPIKey,
    normalize_records,normalize_download,write_normalized,DatabentoProvider,
    ProviderCoverage,DefinitionIndex,OpenInterestIndex,definition,canonical_contract,
    to_ns,ns_time,parse_time,fixed_price,hash_file,redacted,read_jsonl)
from backtester.providers.coverage import DatedSessionCalendar
from backtester.rolls import ContinuousSeries,RollConfig,SelectedBar
from backtester.features import FeatureEngine
from backtester.research import WeeklyVWAPReaction,ReactionConfig,label_events
from backtester.execution import FillModel,Order,OrderRequest,Side,OrderType
from backtester.instruments import instrument
from backtester.intraday import IntradayEngine
from backtester.strategy import NoOrders

UTC=timezone.utc
START=parse_time('2026-09-13T22:00:00Z')


def calendar():
    return DatedSessionCalendar(dict(version='invented-fixture-v1',product='NQ',timezone='America/New_York',
        dates={'2026-09-14':{'breaks':[]},'2026-09-15':{'breaks':[]}},
        source_urls=['fixture://offline-only'],status='TEST FIXTURE'))


def defs():
    available=START-timedelta(hours=12)
    return [dict(hd=dict(ts_event=str(to_ns(available)),instrument_id=identifier),ts_recv=str(to_ns(available)),
        raw_symbol=raw,instrument_class='F',security_update_action='A',expiration=str(to_ns(parse_time(expiry))),
        activation=str(to_ns(START-timedelta(days=30))),min_price_increment='250000000',
        unit_of_measure_qty='20000000000',currency='USD',exchange='XCME',contract_multiplier=1)
        for identifier,raw,expiry in [(101,'NQU6','2026-09-18T13:30:00Z'),(202,'NQZ6','2026-12-18T14:30:00Z'),
                                       (303,'NQH7','2027-03-19T13:30:00Z')]]


def record(stamp,identifier=101,price=20000,volume=10):
    return dict(hd=dict(ts_event=str(to_ns(stamp)),instrument_id=identifier),open=str(round(price*1e9)),
        high=str(round((price+.5)*1e9)),low=str(round((price-.5)*1e9)),close=str(round((price+.25)*1e9)),volume=str(volume))


def fixture(records=None,condition='available',policy='materialize',duration=6,oi=None,oi_policy='retrospective'):
    request=DownloadRequest(START,START+timedelta(minutes=duration))
    coverage=ProviderCoverage(request.start,request.end,[dict(date='2026-09-13',condition=condition),
        dict(date='2026-09-14',condition=condition),dict(date='2026-09-15',condition=condition)],True)
    if records is None:
        records=[record(START+timedelta(minutes=i),identifier,20000+(identifier==202)*100+i*.25)
                 for i in range(duration) for identifier in (101,202)]
    return normalize_records(records,defs(),oi or [],request,coverage,calendar(),policy,2,oi_policy)


def stat(stamp,quantity=123,**kwargs):
    return dict(ts_event=str(to_ns(stamp)),ts_recv=str(to_ns(stamp)+1),ts_ref=str(to_ns(START)),
        instrument_id=101,stat_type=9,stat_flags=0,update_action=1,quantity=quantity,**kwargs)


def persist(tmp_path,bars,audit):
    raw=tmp_path/'raw';raw.mkdir()
    for name,rows in [('definition.jsonl',defs()),('ohlcv-1m.jsonl',[record(b.timestamp,b.instrument_id,b.open,b.volume) for b in bars if b.published]),('statistics.jsonl',[])]:
        (raw/name).write_text(''.join(json.dumps(r)+'\n' for r in rows))
    manifest=dict(download_complete=True,request=audit['request'],download_timestamp='2026-10-05T00:00:00+00:00',
        files={p.name:hash_file(p) for p in raw.iterdir()},conditions=[dict(date='2026-09-13',condition='available')])
    (raw/'manifest.json').write_text(json.dumps(manifest))
    output=tmp_path/'normalized'
    write_normalized(output,bars,audit,manifest,raw)
    return raw,output


def test_timestamp_ohlcv_and_provenance():
    bars,audit=fixture()
    bar=bars[0]
    assert bar.timestamp==START and bar.end==START+timedelta(minutes=1)
    assert (bar.open,bar.high,bar.low,bar.close,bar.volume)==(20000,20000.5,19999.5,20000.25,10)
    assert (bar.contract,bar.raw_symbol,bar.instrument_id)==('NQU26','NQU6',101)
    assert (bar.provider,bar.dataset,bar.schema,bar.published)==('Databento','GLBX.MDP3','ohlcv-1m',True)
    assert bar.source_ts_event_ns==to_ns(START) and len(bar.request_id)==64
    assert audit['request']['symbols']==['NQ.FUT'] and audit['request']['stype_in']=='parent'
    assert [r['contract'] for r in audit['contracts']]==['NQU26','NQZ26']
    assert all(c['tick_value']==5 and c['point_value']==20 and c['tick_size']==.25 for c in audit['contracts'])


@pytest.mark.parametrize('raw',['NQU6','NQU26','NQU2026'])
def test_symbol_year_uses_actual_expiration(raw):
    assert canonical_contract(raw,parse_time('2026-09-18T13:30:00Z'))=='NQU26'


@pytest.mark.parametrize('raw',['NQU5','NQZ6','NQ.c.0','NQU6-NQZ6'])
def test_bad_symbols_rejected(raw):
    with pytest.raises(ValueError):canonical_contract(raw,parse_time('2026-09-18T13:30:00Z'))


@pytest.mark.parametrize('field,value',[('min_price_increment','500000000'),('unit_of_measure_qty','5000000000'),
    ('currency','EUR'),('expiration',str(to_ns(parse_time('2026-09-18T00:00:00Z'))))])
def test_disagreeing_or_ambiguous_definition_rejected(field,value):
    row=defs()[0];row[field]=value
    with pytest.raises(ValueError):definition(row)


def test_definition_versions_are_point_in_time():
    original=defs()[0];future=dict(original,min_price_increment='500000000')
    future['ts_recv']=str(to_ns(START+timedelta(minutes=1)))
    # A disagreement is rejected globally even when it is discovered later.
    with pytest.raises(ValueError,match='economics'):DefinitionIndex([original,future])
    deleted=dict(original,security_update_action='D',ts_recv=str(to_ns(START+timedelta(minutes=1))))
    index=DefinitionIndex([original,deleted])
    assert index.at(101,START)
    assert index.at(101,START+timedelta(minutes=1)) is None
    assert index.at(101,START-timedelta(days=1)) is None


def test_no_trade_is_explicit_unpublished_and_not_backfilled():
    rows=[record(START),record(START+timedelta(minutes=2)),record(START+timedelta(minutes=2),202)]
    bars,audit=fixture(rows,duration=3)
    nt=next(b for b in bars if b.timestamp==START+timedelta(minutes=1))
    assert nt.bar_state=='NO_TRADE' and nt.volume==0 and not nt.published
    assert nt.open==nt.high==nt.low==nt.close==20000.25
    assert audit['states']['NO_TRADE_UNPRICED']==2
    assert not any(b.contract=='NQZ26' and b.timestamp<START+timedelta(minutes=2) for b in bars)
    kept,_=fixture(rows,policy='preserve',duration=3)
    assert len(kept)==3


@pytest.mark.parametrize('condition',['degraded','missing','pending','unknown'])
def test_unknown_coverage_never_filled(condition):
    bars,audit=fixture([record(START),record(START+timedelta(minutes=2),202)],condition,duration=3)
    assert len(bars)==2 and audit['states']['UNKNOWN']==4
    assert all(b.bar_state=='TRADED' and b.coverage_state=='UNKNOWN' for b in bars)


def test_coverage_requires_complete_request():
    coverage=ProviderCoverage(START,START+timedelta(minutes=2),[dict(date='2026-09-13',condition='available')],False)
    assert coverage.at(START).state=='UNKNOWN'
    coverage.completed=True
    assert coverage.at(START+timedelta(minutes=2)).state=='UNKNOWN'


@pytest.mark.parametrize('mutator',[
    lambda rows:rows+[rows[0]],
    lambda rows:[dict(rows[0],hd=dict(instrument_id=999,ts_event=to_ns(START)))],
    lambda rows:[dict(rows[0],hd=dict(instrument_id=101,ts_event=to_ns(START)+1))],
    lambda rows:[dict(rows[0],volume='0')]])
def test_invalid_provider_records_fail(mutator):
    with pytest.raises(ValueError):fixture(mutator([record(START)]))


def test_deterministic_normalization_includes_input_reordering_audit():
    rows=[record(START+timedelta(minutes=i),identifier) for i in range(3) for identifier in (101,202)]
    one,a=fixture(rows,duration=3);two,b=fixture(list(reversed(rows)),duration=3)
    assert one==two and b['source_out_of_order_records']>0
    assert fixture(rows,duration=3)==(one,a)


def test_oi_retrospective_default_and_capture_bound_rounds_up():
    rows=[stat(START+timedelta(minutes=1))]
    assert OpenInterestIndex(rows).at(101,START+timedelta(hours=1)) is None
    index=OpenInterestIndex(rows,'capture-time')
    assert index.at(101,START+timedelta(minutes=1)) is None
    assert index.at(101,START+timedelta(minutes=1,microseconds=1))['quantity']==123
    bars,audit=fixture(oi=rows,oi_policy='capture-time')
    assert bars[0].open_interest is None
    assert next(b for b in bars if b.contract=='NQU26' and b.timestamp==START+timedelta(minutes=2)).open_interest==123
    assert audit['open_interest_observations'][0]['available_at']==START+timedelta(minutes=1,microseconds=1)


@pytest.mark.parametrize('change',[dict(stat_flags=1),dict(ts_recv=None),dict(update_action=3),dict(ts_ref=str(to_ns(START+timedelta(days=1))))])
def test_uncertain_oi_is_retrospective(change):
    row=stat(START);row.update(change)
    index=OpenInterestIndex([row],'capture-time')
    assert index.records[0]['state']=='RETROSPECTIVE' and index.at(101,START+timedelta(days=1)) is None


def test_oi_deletion_does_not_reuse_previous_value():
    rows=[stat(START),dict(stat(START+timedelta(minutes=1)),update_action=2,quantity=2**63-1)]
    index=OpenInterestIndex(rows,'capture-time')
    assert index.at(101,START+timedelta(minutes=2))['state']=='DELETED'
    bars,_=fixture(oi=rows,oi_policy='capture-time')
    assert next(b for b in bars if b.contract=='NQU26' and b.timestamp==START+timedelta(minutes=2)).open_interest is None


def test_hashes_and_roundtrip(tmp_path):
    bars,audit=fixture();raw,output=persist(tmp_path,bars,audit)
    loaded,_=DatabentoProvider(output/'bars.csv').load()
    assert loaded==bars
    assert len(json.loads((output/'metadata.json').read_text())['source_hashes'])==3
    again=tmp_path/'again'
    payload=normalize_download(raw,again,calendar(),'materialize',2)
    assert hash_file(again/'bars.csv')==hash_file(output/'bars.csv')==payload['normalized_sha256']
    with pytest.raises(FileExistsError):normalize_download(raw,again,calendar())
    (raw/'ohlcv-1m.jsonl').write_text('tampered')
    with pytest.raises(ValueError,match='hash'):DatabentoProvider(output/'bars.csv')
    with pytest.raises(ValueError,match='hash'):normalize_download(raw,tmp_path/'bad',calendar())


def test_normalized_tamper_rejected(tmp_path):
    bars,audit=fixture();_,out=persist(tmp_path,bars,audit)
    with (out/'bars.csv').open('a') as stream:stream.write('\n')
    with pytest.raises(ValueError,match='hash'):DatabentoProvider(out/'bars.csv')


def test_dated_calendar_fails_outside_bounds_and_removes_obsolete_halt():
    doc = dict(calendar().document)
    doc['dates'] = {(date(2026, 9, 14) + timedelta(days=i)).isoformat(): {'breaks': []}
                    for i in range(12) if (date(2026, 9, 14) + timedelta(days=i)).weekday() < 5}
    cal = DatedSessionCalendar(doc)
    assert cal.classify(parse_time('2026-09-14T20:20:00Z')).session=='POST_RTH'
    assert cal.classify(parse_time('2026-09-14T21:30:00Z')) is None
    assert cal.classify(START).trading_date==date(2026,9,14)
    assert cal.classify(parse_time('2026-09-19T15:00:00Z')) is None
    with pytest.raises(ValueError,match='does not cover'):cal.classify(parse_time('2026-09-28T15:00:00Z'))
    cal.verify_range(START,parse_time('2026-09-25T21:00:00Z'))


def test_calendar_override_closure_early_close_and_halt():
    doc=dict(calendar().document)
    doc['dates']={'2026-09-14':dict(eth_close='13:00',rth_close='13:00',breaks=[['10:00','10:05']]),'2026-09-15':dict(closed=True)}
    cal=DatedSessionCalendar(doc)
    assert cal.classify(parse_time('2026-09-14T14:02:00Z')) is None
    assert cal.classify(parse_time('2026-09-14T17:00:00Z')) is None
    assert cal.classify(parse_time('2026-09-15T15:00:00Z')) is None


def test_no_trade_never_triggers_fill_or_changes_price_extrema():
    bars,_=fixture([record(START),record(START+timedelta(minutes=2)),record(START,202)],duration=3)
    nt=next(b for b in bars if b.contract=='NQU26' and b.bar_state=='NO_TRADE')
    model=FillModel(instrument('NQ'))
    order=Order(1,START,date(2026,9,14),'NQU26',OrderRequest(Side.BUY,type=OrderType.STOP,price=nt.close))
    assert model.fill(order,nt,100) is None and not order.triggered
    feature=FeatureEngine(calendar(),atr_period=1)
    first=next(b for b in bars if b.contract=='NQU26')
    a=feature.update(first);b=feature.update(nt)
    assert a['ATR']==b['ATR'] and a['ONH']==b['ONH'] and a['ONL']==b['ONL']
    assert a['weekly_vwap']==b['weekly_vwap']
    assert b['weekly_vwap_complete']


def test_unknown_bar_invalidates_feature_completeness():
    bars,_=fixture(condition='degraded')
    values=FeatureEngine(calendar()).update(bars[0])
    assert not values['weekly_vwap_complete'] and not values['session_vwap_complete']


def test_no_trade_cannot_create_events_and_unknown_censors_labels():
    bars,_=fixture([record(START),record(START,202)],duration=6)
    selected=tuple(SelectedBar(b,b) for b in bars if b.contract=='NQU26')
    strategy=WeeklyVWAPReaction(ReactionConfig(require_complete_week=False))
    IntradayEngine(instrument('NQ'),calendar(),strategy).run(selected)
    assert not strategy.events
    event=dict(timestamp=START+timedelta(minutes=1),contract='NQU26',reference_level=20000,
        research_scale=1,away_direction=1,trading_date=date(2026,9,14))
    cfg=ReactionConfig(horizons_minutes=(5,))
    labels=label_events([event],selected,calendar(),cfg)
    assert labels[0]['forward']['5']['complete'] and labels[0]['forward']['5']['mfe_points']==0
    changed=list(selected);bar=replace(changed[0].raw,coverage_state='UNKNOWN')
    changed[0]=SelectedBar(bar,bar)
    ev=dict(event,timestamp=START)
    label=label_events([ev],changed,calendar(),cfg)[0]
    assert not label['forward']['5']['complete'] and label['forward']['5']['censored_reason']=='unknown_provider_coverage'


def test_completed_session_volume_roll_and_sparse_third_contract():
    cal=calendar();request=DownloadRequest(START,parse_time('2026-09-15T22:00:00Z')-timedelta(hours=1))
    rows=[];stamp=request.start
    while stamp<request.end:
        if cal.valid_bar(stamp,timedelta(minutes=1)):
            for identifier in (101,202):
                rows.append(record(stamp,identifier,20000+(identifier==202)*100,5 if identifier==101 else 10))
            if stamp==START:rows.append(record(stamp,303,20200,1))
        stamp+=timedelta(minutes=1)
    coverage=ProviderCoverage(request.start,request.end,[dict(date=d,condition='available') for d in ['2026-09-13','2026-09-14','2026-09-15']],True)
    bars,_=normalize_records(rows,defs(),[],request,coverage,cal,'materialize',3)
    cfg=RollConfig(policy='volume',initial_contract='NQU26',expirations={'NQU26':'2026-09-18','NQZ26':'2026-12-18','NQH27':'2027-03-19'},defer_until_traded_pair=True)
    series=ContinuousSeries(cal,cfg);selected=tuple(series.select(bars))
    assert len(series.records)==1 and series.records[0].timestamp==parse_time('2026-09-14T22:00:00Z')
    assert selected[0].raw.contract=='NQU26' and selected[-1].raw.contract=='NQZ26'
    rolled=next(item for item in selected if item.roll)
    assert rolled.research.open==20000 and rolled.roll.price_difference==100


def test_roll_waits_for_traded_pair():
    bars,_=fixture([record(START),record(START,202),record(START+timedelta(minutes=1)),record(START+timedelta(minutes=2)),record(START+timedelta(minutes=2),202)],duration=3)
    # On Monday, fixed policy already selects a roll; first old/new pair is traded.
    cfg=RollConfig(policy='fixed',expirations={'NQU26':'2026-09-18','NQZ26':'2026-12-18'},days_before_expiration=4,defer_until_traded_pair=True)
    assert tuple(ContinuousSeries(calendar(),cfg).select(bars))[0].roll
    # Delete new first print while keeping its previous known price for an explicit grid bar.
    new=next(b for b in bars if b.contract=='NQZ26')
    nt=replace(new,open=new.close,high=new.close,low=new.close,volume=0,bar_state='NO_TRADE',published=False,source_ts_event_ns=None)
    panel=tuple(nt if b==new else b for b in bars)
    series=ContinuousSeries(calendar(),cfg);selected=tuple(series.select(panel))
    assert not selected[0].roll and series.records[0].timestamp==START+timedelta(minutes=2)


def test_key_missing_and_error_redaction(monkeypatch,capsys):
    monkeypatch.delenv('DATABENTO_API_KEY',raising=False)
    with pytest.raises(MissingAPIKey):HistoricalGateway()
    from backtester.provider_cli import main
    monkeypatch.setattr(sys,'argv',['backtester','download','--start','2026-09-13T22:00:00Z','--end','2026-09-14T21:00:00Z','--estimate-only'])
    main();assert 'SKIPPED' in capsys.readouterr().out
    fake='db-'+'offline-fixture-only'*2
    monkeypatch.setenv('DATABENTO_API_KEY',fake)
    encoded=base64.b64encode((fake+':').encode()).decode()
    assert fake not in redacted(fake+' '+encoded) and encoded not in redacted(fake+' '+encoded)
    gateway=HistoricalGateway(SimpleNamespace())
    def error():raise ValueError(fake+' '+encoded)
    with pytest.raises(RuntimeError) as caught:gateway.call('test',error)
    assert fake not in str(caught.value) and encoded not in str(caught.value)


def test_request_definition_bounds_and_estimates():
    request=DownloadRequest(START,parse_time('2026-09-25T21:00:00Z'))
    assert request.kwargs('definition')['start']=='2026-09-13T00:00:00+00:00'
    assert request.kwargs('definition')['end']=='2026-09-26T00:00:00+00:00'
    received=[]
    def cost(**kwargs):received.append(kwargs);return .25
    metadata=SimpleNamespace(get_cost=cost,get_billable_size=lambda **kw:1000,get_record_count=lambda **kw:100)
    estimate=HistoricalGateway(SimpleNamespace(metadata=metadata)).estimate(request)
    assert estimate['total_cost_usd']==.75 and len(received)==3
    assert all(q['symbols']==['NQ.FUT'] and q['stype_in']=='parent' for q in received)


def test_cost_ceiling_blocks_before_download(monkeypatch,capsys,tmp_path):
    import backtester.provider_cli as cli
    class Gateway:
        def estimate(self,request):return dict(total_cost_usd=2)
        def download(self,*args):pytest.fail('Must not incur a download')
    monkeypatch.setattr(cli,'HistoricalGateway',Gateway)
    monkeypatch.setattr(sys,'argv',['backtester','download','--start','2026-09-14','--end','2026-09-15','--max-cost-usd','1','--output',str(tmp_path/'data')])
    with pytest.raises(SystemExit):cli.main()
    assert not (tmp_path/'data').exists()
    assert 'exceeds authorized' in capsys.readouterr().err


def test_official_sdk_fixed_point_export_roundtrip(tmp_path):
    db=pytest.importorskip('databento');d=pytest.importorskip('databento_dbn')
    row=record(START)
    msg=d.OHLCVMsg(rtype=d.RType.OHLCV_1M,publisher_id=1,instrument_id=101,ts_event=to_ns(START),
        open=int(row['open']),high=int(row['high']),low=int(row['low']),close=int(row['close']),volume=10)
    metadata=d.Metadata(dataset='GLBX.MDP3',start=to_ns(START),end=to_ns(START+timedelta(minutes=1)),
        stype_in=d.SType.PARENT,stype_out=d.SType.INSTRUMENT_ID,schema=d.Schema.OHLCV_1M,symbols=['NQ.FUT'])
    path=tmp_path/'raw.dbn';path.write_bytes(bytes(metadata)+bytes(msg))
    store=db.DBNStore.from_file(path);store.to_json(tmp_path/'bars.jsonl',pretty_px=False,pretty_ts=False,map_symbols=False,mode='x')
    exported=read_jsonl(tmp_path/'bars.jsonl')
    bars,_=fixture(exported,duration=1)
    assert bars[0].timestamp==START and bars[0].open==20000 and bars[0].instrument_id==101


@pytest.mark.integration
def test_live_databento_metadata_only():
    if os.environ.get('BACKTESTER_LIVE_TESTS')!='1' or not os.environ.get('DATABENTO_API_KEY'):
        pytest.skip('Requires explicit live opt-in and environment API key')
    gateway=HistoricalGateway()
    request=DownloadRequest(START,parse_time('2026-09-25T21:00:00Z'))
    assert gateway.estimate(request)['total_cost_usd']>=0
    assert gateway.metadata(request)['conditions']


def test_gateway_download_preserves_raw_exports_and_readonly_files(tmp_path):
    db=pytest.importorskip('databento');d=pytest.importorskip('databento_dbn')
    request=DownloadRequest(START,START+timedelta(minutes=3))
    def get_range(path,**kwargs):
        schema=kwargs['schema'];start=to_ns(parse_time(kwargs['start']));end=to_ns(parse_time(kwargs['end']))
        meta=d.Metadata(dataset='GLBX.MDP3',start=start,end=end,stype_in=d.SType.PARENT,
            stype_out=d.SType.INSTRUMENT_ID,schema=d.Schema(schema),symbols=['NQ.FUT'])
        messages=[]
        if schema=='definition':
            for row in defs():
                messages.append(d.InstrumentDefMsg(publisher_id=1,instrument_id=row['hd']['instrument_id'],
                    ts_event=int(row['hd']['ts_event']),ts_recv=int(row['ts_recv']),min_price_increment=int(row['min_price_increment']),
                    display_factor=10**9,raw_symbol=row['raw_symbol'],asset='NQ',security_type='FUT',
                    instrument_class=d.InstrumentClass.FUTURE,security_update_action=d.SecurityUpdateAction.ADD,
                    expiration=int(row['expiration']),activation=int(row['activation']),unit_of_measure_qty=int(row['unit_of_measure_qty']),
                    currency='USD',exchange='XCME',contract_multiplier=1))
        elif schema=='ohlcv-1m':
            for i in range(3):
                for identifier in (101,202):
                    row=record(START+timedelta(minutes=i),identifier)
                    messages.append(d.OHLCVMsg(rtype=d.RType.OHLCV_1M,publisher_id=1,instrument_id=identifier,
                        ts_event=int(row['hd']['ts_event']),open=int(row['open']),high=int(row['high']),low=int(row['low']),
                        close=int(row['close']),volume=int(row['volume'])))
        path.write_bytes(bytes(meta)+b''.join(bytes(m) for m in messages))
        return db.DBNStore.from_file(path)
    gateway=HistoricalGateway(SimpleNamespace(timeseries=SimpleNamespace(get_range=get_range)))
    raw=tmp_path/'raw'
    manifest=gateway.download(request,raw,dict(total_cost_usd=0),dict(conditions=[dict(date='2026-09-13',condition='available')]))
    assert manifest['download_complete'] and len(manifest['files'])==7
    assert all(p.stat().st_mode & 0o222==0 for p in raw.iterdir())
    out=tmp_path/'normalized';normalize_download(raw,out,calendar(),'materialize',2)
    bars,_=DatabentoProvider(out/'bars.csv').load()
    assert len(bars)==6 and bars[0].raw_symbol=='NQU6'
    from backtester.provider_cli import inspect_provider
    audit=inspect_provider(out/'bars.csv',out/'research-config.json',4)
    assert len(audit['samples'])==3 and all(s['matches_retained_raw'] for s in audit['samples'])
    with pytest.raises(FileExistsError):gateway.download(request,raw,{}, {})


def test_gateway_incomplete_download_is_not_normalized(tmp_path):
    def fail(**kwargs):raise RuntimeError('invented failure')
    gateway=HistoricalGateway(SimpleNamespace(timeseries=SimpleNamespace(get_range=fail)))
    raw=tmp_path/'raw'
    with pytest.raises(RuntimeError):gateway.download(DownloadRequest(START,START+timedelta(minutes=1)),raw,{}, {})
    assert (raw/'failure.json').exists() and not (raw/'manifest.json').exists()
    with pytest.raises(FileNotFoundError):normalize_download(raw,tmp_path/'out',calendar())


def test_gateway_truncated_dbn_metadata_fails(tmp_path):
    request=DownloadRequest(START,START+timedelta(minutes=1))
    store=SimpleNamespace(metadata=SimpleNamespace(limit=1))
    gateway=HistoricalGateway(SimpleNamespace(timeseries=SimpleNamespace(get_range=lambda **kw:store)))
    with pytest.raises(ValueError,match='untruncated'):gateway.download(request,tmp_path/'raw',{}, {})
    assert not (tmp_path/'raw'/'manifest.json').exists()


def test_cli_uses_provider_calendar_and_snapshots_modules(tmp_path):
    from backtester.cli import objects,code_snapshot
    bars,audit=fixture();_,out=persist(tmp_path,bars,audit)
    args=SimpleNamespace(data=out/'bars.csv',symbol='NQ',interval=1,contract=None)
    config=json.loads((out/'research-config.json').read_text())
    ins,cal,provider=objects(args,config)
    assert isinstance(provider,DatabentoProvider) and cal.breaks==[] and ins.symbol=='NQ'
    assert 'providers/databento.py' in code_snapshot()['files']
    config['calendar']['breaks']=[['16:15','16:30']]
    with pytest.raises(ValueError,match='disagrees'):objects(args,config)


def test_normalized_provider_weekly_cli_smoke(tmp_path,monkeypatch,capsys):
    from backtester.cli import main
    bars,audit=fixture();_,out=persist(tmp_path,bars,audit)
    results=tmp_path/'results'
    monkeypatch.setattr(sys,'argv',['backtester','run','--symbol','NQ','--data',str(out/'bars.csv'),
        '--config',str(out/'research-config.json'),'--output',str(results)])
    main()
    assert 'Events:' in capsys.readouterr().out
    run=next(results.iterdir())
    metadata=json.loads((run/'metadata.json').read_text())
    assert metadata['provider_provenance']['provider']=='Databento'
    assert metadata['dated_calendar']['document']['version']=='invented-fixture-v1'
    assert 'providers/databento.py' in metadata['code']['files']


def test_schema_availability_is_checked_before_download():
    request=DownloadRequest(START,START+timedelta(minutes=1))
    def ranges(**kwargs):
        return dict(start='2010-01-01T00:00:00Z',end='2030-01-01T00:00:00Z',
            schema={'statistics':dict(start='2026-09-14T00:00:00Z',end='2030-01-01T00:00:00Z')})
    metadata=SimpleNamespace(get_dataset_range=ranges,get_dataset_condition=lambda **kw:[])
    with pytest.raises(ValueError,match='statistics'):HistoricalGateway(SimpleNamespace(metadata=metadata)).metadata(request)


def test_explicit_history_scope_accepts_only_quarterly_nq_outrights():
    req=DownloadRequest(START,START+timedelta(days=28),symbols=('NQU6','NQZ6','NQH7'),stype_in='raw_symbol',schemas=('definition','ohlcv-1m'))
    assert req.kwargs()['symbols']==['NQU6','NQZ6','NQH7']
    assert req.kwargs()['stype_in']=='raw_symbol'
    assert req.kwargs('definition')['start'].endswith('00:00+00:00')
    with pytest.raises(ValueError,match='quarterly NQ outrights'):
        DownloadRequest(START,START+timedelta(days=1),symbols=('NQU6-NQZ6',),stype_in='raw_symbol')
