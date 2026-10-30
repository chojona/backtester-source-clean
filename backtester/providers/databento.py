"""Databento Historical boundary; secrets and SDK objects stay outside core logic."""
from dataclasses import dataclass,asdict
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from math import isfinite
import hashlib,json,logging,os,re
from ..data import Bar,DataProvider,IntegrityReport,validate,CSVProvider,_mint_verified_open_interest
from ..instruments import instrument
from ..sessions import NY
from .coverage import ProviderCoverage,DatedSessionCalendar

NORMALIZER_VERSION='1.0.0'
DATASET='GLBX.MDP3'
SDK_VERSION='0.87.0'
NANO=1_000_000_000
EPOCH=datetime(1970,1,1,tzinfo=timezone.utc)
NULL_TIME=2**64-1
NULL_PRICE=2**63-1


class MissingAPIKey(Exception):
    pass


def parse_time(value):
    if isinstance(value,datetime):
        result=value
    else:
        value=str(value)
        if len(value)==10:
            value+='T00:00:00+00:00'
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:
        raise ValueError('Request timestamps must have an offset (bare dates mean midnight UTC)')
    return result.astimezone(timezone.utc)


def ns_time(value,ceil=False):
    if value is None or str(value) in (str(NULL_TIME),'0',''):
        return None
    value=int(value)
    if value<0 or value>=NULL_TIME:
        raise ValueError('Invalid provider nanosecond timestamp')
    seconds,nanos=divmod(value,NANO)
    micros=(nanos+999)//1000 if ceil else nanos//1000
    return EPOCH+timedelta(seconds=seconds,microseconds=micros)


def to_ns(stamp):
    difference=stamp-EPOCH
    return (difference.days*86400+difference.seconds)*NANO+difference.microseconds*1000


def fixed_price(value):
    value=int(value)
    if value==NULL_PRICE:
        raise ValueError('Undefined provider price')
    return float(Decimal(value)/Decimal(NANO))


def flat_record(record):
    result=dict(record.get('hd',{}))
    result.update({k:v for k,v in record.items() if k!='hd'})
    return result


def hash_file(path):
    with Path(path).open('rb') as stream:
        digest=hashlib.sha256()
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path):
    with Path(path).open() as stream:
        return [flat_record(json.loads(line)) for line in stream if line.strip()]


def json_write(path,payload,exclusive=True):
    with Path(path).open('x' if exclusive else 'w') as stream:
        json.dump(payload,stream,sort_keys=True,indent=2,allow_nan=False,default=lambda v:v.isoformat() if isinstance(v,datetime) else v)
        stream.write('\n')


def redacted(text):
    """Last-resort diagnostic sanitizer; normal API errors discard SDK payloads entirely."""
    import base64
    key=os.environ.get('DATABENTO_API_KEY')
    if key:
        text=text.replace(key,'[REDACTED]').replace(base64.b64encode((key+':').encode()).decode(),'[REDACTED]')
    return re.sub(r'db-[A-Za-z0-9_-]{20,}', '[REDACTED]',text)


@dataclass(frozen=True)
class DownloadRequest:
    start: object
    end: object
    dataset: str=DATASET
    schema: str='ohlcv-1m'
    symbols: tuple=('NQ.FUT',)
    stype_in: str='parent'
    symbol: str='NQ'
    schemas: tuple=('ohlcv-1m','definition','statistics')

    def __post_init__(self):
        object.__setattr__(self,'start',parse_time(self.start))
        object.__setattr__(self,'end',parse_time(self.end))
        object.__setattr__(self,'symbols',tuple(self.symbols))
        object.__setattr__(self,'schemas',tuple(self.schemas))
        if self.dataset!=DATASET or self.schema!='ohlcv-1m' or self.symbol!='NQ' or not self.symbols:
            raise ValueError('Adapter requires GLBX.MDP3 / ohlcv-1m / NQ instruments')
        if self.stype_in=='parent':
            if self.symbols!=('NQ.FUT',): raise ValueError('Parent symbology requires NQ.FUT')
        elif self.stype_in=='raw_symbol':
            if any(not re.fullmatch(r'NQ[HMUZ]\d{1,4}',str(s)) for s in self.symbols):
                raise ValueError('Raw-symbol requests must contain only quarterly NQ outrights')
        else:
            raise ValueError('Use parent NQ.FUT or explicit quarterly raw-symbol outrights')
        if set(self.schemas)-{'ohlcv-1m','definition','statistics'} or 'ohlcv-1m' not in self.schemas or 'definition' not in self.schemas:
            raise ValueError('Unsupported schema set')
        if self.end<=self.start or any(to_ns(t)%(60*NANO) for t in (self.start,self.end)):
            raise ValueError('Request must have increasing minute-aligned timestamps')

    def kwargs(self,schema=None):
        start,end=self.start,self.end
        if schema=='definition':
            start=start.replace(hour=0,minute=0,second=0,microsecond=0)
            end=(end-timedelta(microseconds=1)).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
        return dict(dataset=self.dataset,schema=schema or self.schema,start=start.isoformat(),end=end.isoformat(),
                    symbols=list(self.symbols),stype_in=self.stype_in)


class HistoricalGateway:
    def __init__(self,client=None):
        if client is None:
            key=os.environ.get('DATABENTO_API_KEY')
            if not key:
                raise MissingAPIKey('DATABENTO_API_KEY is not set; live request skipped')
            try:
                import databento as db
                for name in ('databento','httpx','httpcore','urllib3'):
                    logging.getLogger(name).setLevel(logging.CRITICAL)
                client=db.Historical(key=key)
            except ImportError:
                raise RuntimeError('Install the databento optional dependency in Python 3.12') from None
            except Exception:
                raise RuntimeError('Databento client initialization failed; credentials and SDK diagnostics withheld') from None
        self.client=client

    def call(self,name,function,**kwargs):
        try:
            return function(**kwargs)
        except Exception:
            raise RuntimeError('Databento '+name+' failed; SDK diagnostics withheld to prevent credential disclosure') from None

    def estimate(self,request):
        results={}
        for schema in request.schemas:
            kwargs=request.kwargs(schema)
            cost=self.call('cost estimate',self.client.metadata.get_cost,**kwargs)
            size=self.call('size estimate',self.client.metadata.get_billable_size,**kwargs)
            count=self.call('record estimate',self.client.metadata.get_record_count,**kwargs)
            if not isfinite(cost) or cost<0 or size<0 or count<0:
                raise ValueError('Invalid provider estimate')
            results[schema]=dict(request=kwargs,cost_usd=cost,billable_bytes=size,records=count)
        return dict(provider='Databento',requests=results,total_cost_usd=sum(v['cost_usd'] for v in results.values()),
                    note='Provider estimate, not a guaranteed invoice; definition estimate uses whole UTC days')

    def metadata(self,request):
        conditions=self.call('dataset conditions',self.client.metadata.get_dataset_condition,dataset=request.dataset,
                             start_date=request.start.date().isoformat(),end_date=(request.end-timedelta(microseconds=1)).date().isoformat())
        available=self.call('dataset range',self.client.metadata.get_dataset_range,dataset=request.dataset)
        schemas=available.get('schema',{})
        for schema in request.schemas:
            bounds=schemas.get(schema,available)
            kwargs=request.kwargs(schema)
            if parse_time(bounds['start'])>parse_time(kwargs['start']) or parse_time(bounds['end'])<parse_time(kwargs['end']):
                raise ValueError('Requested '+schema+' range is not fully available')
        return dict(conditions=conditions,dataset_range=available)

    def download(self,request,raw_directory,estimate,coverage_metadata):
        raw_directory=Path(raw_directory)
        raw_directory.mkdir(parents=True,exist_ok=False)
        status=dict(provider='Databento',sdk_version=SDK_VERSION,request=request.kwargs(),
                    schemas=list(request.schemas),
                    download_started=datetime.now(timezone.utc),download_complete=False,
                    estimate=estimate,**coverage_metadata)
        json_write(raw_directory/'request.json',status)
        files={'request.json':hash_file(raw_directory/'request.json')}
        dbn_metadata={}
        try:
            for schema in request.schemas:
                path=raw_directory/(schema+'.dbn.zst')
                store=self.call(schema+' download',self.client.timeseries.get_range,**request.kwargs(schema),path=path)
                meta=store.metadata
                params=request.kwargs(schema)
                if (meta.limit is not None or meta.partial or meta.not_found or
                    meta.dataset!=request.dataset or str(meta.schema)!=schema or
                    meta.start>to_ns(parse_time(params['start'])) or meta.end is None or
                    meta.end<to_ns(parse_time(params['end']))):
                    raise ValueError('DBN metadata does not establish a full untruncated request')
                dbn_metadata[schema]=dict(start=meta.start,end=meta.end,limit=meta.limit,
                    dataset=meta.dataset,schema=str(meta.schema),symbols=meta.symbols,
                    partial=meta.partial,not_found=meta.not_found,stype_in=str(meta.stype_in))
                export=raw_directory/(schema+'.jsonl')
                self.call(schema+' fixed-point export',store.to_json,path=export,pretty_px=False,pretty_ts=False,map_symbols=False,mode='x')
                files[path.name]=hash_file(path)
                files[export.name]=hash_file(export)
        except BaseException as exc:
            state='INTERRUPTED_BY_USER' if isinstance(exc,KeyboardInterrupt) else 'FAILED'
            json_write(raw_directory/'failure.json',dict(status=state,exception_type=type(exc).__name__,
                note='Partial raw files retained; no normalization allowed and no automatic retry'))
            raise
        status.update(download_complete=True,download_timestamp=datetime.now(timezone.utc),files=files,dbn_metadata=dbn_metadata)
        json_write(raw_directory/'manifest.json',status)
        # Write-once convention plus read-only files. Directory can still be changed by its owner.
        for path in raw_directory.iterdir():
            path.chmod(0o444)
        return status


def canonical_contract(raw_symbol,expiration):
    match=re.fullmatch(r'NQ([HMUZ])(\d{1}|\d{2}|\d{4})',raw_symbol)
    if not match:
        raise ValueError('Not an NQ quarterly outright: '+raw_symbol)
    suffix=match.group(2)
    year=str(expiration.year)
    if not year.endswith(suffix):
        raise ValueError('Raw symbol year disagrees with provider expiration metadata')
    months={'H':3,'M':6,'U':9,'Z':12}
    if months[match.group(1)]!=expiration.month:
        raise ValueError('Raw symbol month disagrees with provider expiration metadata')
    return 'NQ'+match.group(1)+year[-2:]


def definition(record):
    record=flat_record(record)
    raw=str(record.get('raw_symbol','')).rstrip('\x00')
    if str(record.get('instrument_class',''))!='F' or not re.fullmatch(r'NQ[HMUZ](\d{1}|\d{2}|\d{4})',raw):
        return None
    expiration=ns_time(record.get('expiration'))
    if expiration is None:
        raise ValueError('NQ definition lacks provider expiration: '+raw)
    available=max((t for t in (ns_time(record.get('ts_recv'),True),ns_time(record.get('ts_event'),True)) if t is not None),default=None)
    if available is None:
        raise ValueError('Definition has no known availability timestamp')
    if expiration.time().isoformat()=='00:00:00':
        raise ValueError('Expiration has ambiguous UTC date-only precision; obtain verified last-trade time before normalization')
    tick=fixed_price(record['min_price_increment'])
    point=fixed_price(record['unit_of_measure_qty'])
    internal=instrument('NQ')
    if abs(tick-internal.tick_size)>1e-10 or abs(point-internal.point_value)>1e-10:
        raise ValueError('Provider NQ tick/point economics disagree with internal definitions')
    if record.get('currency','USD')!='USD' or record.get('exchange','XCME') not in ('XCME','CME'):
        raise ValueError('Unexpected NQ currency/exchange metadata')
    return dict(instrument_id=int(record['instrument_id']),raw_symbol=raw,
                contract=canonical_contract(raw,expiration),expiration=expiration,activation=ns_time(record.get('activation')),
                available_at=available,tick_size=tick,point_value=point,tick_value=tick*point,
                currency=record.get('currency','USD'),contract_multiplier=None if record.get('contract_multiplier')==2**31-1 else record.get('contract_multiplier'),
                raw_contract_multiplier=record.get('contract_multiplier'),
                unit_of_measure=record.get('unit_of_measure'),security_update_action=record.get('security_update_action','A'),
                source_ts_event_ns=record.get('ts_event'),source_ts_recv_ns=record.get('ts_recv'))


class DefinitionIndex:
    def __init__(self,records):
        self.records=[]
        self.by_id={}
        for row in records:
            item=definition(row)
            if item:
                self.records.append(item)
                self.by_id.setdefault(item['instrument_id'],[]).append(item)
        self.records.sort(key=lambda x:(x['available_at'],x['instrument_id']))
        for values in self.by_id.values():
            values.sort(key=lambda x:x['available_at'])
            for first,second in zip(values,values[1:]):
                if first['available_at']==second['available_at'] and first!=second:
                    raise ValueError('Conflicting provider definitions at one timestamp')

    def at(self,instrument_id,stamp):
        from bisect import bisect_right
        versions=self.by_id.get(int(instrument_id),[])
        index=bisect_right([v['available_at'] for v in versions],stamp)-1
        if index<0:
            return None
        item=versions[index]
        if item['security_update_action']=='D' or stamp>=item['expiration'] or (item['activation'] is not None and stamp<item['activation']):
            return None
        return item


class OpenInterestIndex:
    def __init__(self,records,policy='retrospective'):
        if policy not in ('retrospective','capture-time'):
            raise ValueError('Unknown OI availability policy')
        self.records=[]
        self.by_id={}
        for row in records:
            row=flat_record(row)
            if int(row.get('stat_type',0))!=9:
                continue
            event,recv,reference=ns_time(row.get('ts_event'),True),ns_time(row.get('ts_recv'),True),ns_time(row.get('ts_ref'),True)
            verified=policy=='capture-time' and event is not None and recv is not None and row.get('stat_flags') is not None and int(row['stat_flags'])==0 and int(row.get('update_action',0)) in (1,2)
            available=max(event,recv) if verified else None
            if reference is not None and available is not None and reference>available:
                verified=False
                available=None
            deleted=int(row.get('update_action',1))==2
            quantity=int(row['quantity'])
            if not deleted and (quantity==NULL_PRICE or quantity<0):
                raise ValueError('Invalid open interest quantity')
            observation=dict(instrument_id=int(row['instrument_id']),quantity=None if deleted else quantity,reference_time=reference,
                             available_at=available,state='DELETED' if deleted and verified else 'CAUSAL_CAPTURE_BOUND' if verified else 'RETROSPECTIVE',
                             source_ts_event_ns=row.get('ts_event'),source_ts_recv_ns=row.get('ts_recv'))
            self.records.append(observation)
            if verified:
                self.by_id.setdefault(observation['instrument_id'],[]).append(observation)
        for values in self.by_id.values():
            values.sort(key=lambda x:x['available_at'])

    def at(self,instrument_id,stamp):
        eligible=[v for v in self.by_id.get(instrument_id,[]) if v['available_at']<=stamp]
        if not eligible:
            return None
        return eligible[-1]


def normalize_records(records,definitions,statistics,request,coverage,calendar,no_trade_policy='preserve',nearby_contracts=3,oi_policy='retrospective'):
    """Pure normalization: no network, no implicit fill of unknown coverage."""
    if no_trade_policy not in ('preserve','materialize') or nearby_contracts<2:
        raise ValueError('Use preserve/materialize and at least two nearby contracts')
    calendar.verify_range(request.start,request.end)
    index=DefinitionIndex(definitions)
    oi=OpenInterestIndex(statistics,oi_policy)
    initial={}
    for identifier in index.by_id:
        item=index.at(identifier,request.start)
        if item:
            initial[item['contract']]=item
    ordered=sorted(initial.values(),key=lambda x:(x['expiration'],x['contract']))[:nearby_contracts]
    if len(ordered)<2:
        raise ValueError('Need at least two nonexpired NQ constituents known at request start; retrieve a definition snapshot before the range')
    wanted={item['contract'] for item in ordered}
    all_ids={int(flat_record(r)['instrument_id']) for r in definitions}
    request_id=hashlib.sha256(json.dumps(request.kwargs(),sort_keys=True).encode()).hexdigest()
    traded={}
    raw_count=0
    discarded=0
    prior_stamp=None
    source_reordering=0
    for record in records:
        row=flat_record(record)
        identifier=int(row['instrument_id'])
        stamp=ns_time(row['ts_event'])
        if stamp is None or int(row['ts_event'])%(60*NANO):
            raise ValueError('Provider OHLCV ts_event is not minute aligned')
        if not request.start<=stamp<request.end:
            raise ValueError('Provider bar outside requested range')
        raw_count+=1
        if prior_stamp is not None and stamp<prior_stamp:
            source_reordering+=1
        prior_stamp=stamp
        info=index.at(identifier,stamp)
        if info is None:
            if identifier in all_ids and identifier not in index.by_id:
                discarded+=1
                continue
            raise ValueError('OHLCV has no eligible point-in-time definition for ID '+str(identifier))
        if info['contract'] not in wanted:
            discarded+=1
            continue
        key=(stamp,info['contract'])
        if key in traded:
            raise ValueError('Duplicate OHLCV record for a contract and minute')
        if not calendar.valid_bar(stamp,timedelta(minutes=1)):
            raise ValueError('Provider traded bar conflicts with dated calendar; inspect timestamp and source schedule')
        assessment=coverage.at(stamp)
        observation=oi.at(identifier,stamp)
        fields=dict(bar_state='TRADED',coverage_state=assessment.state,
                    provider='Databento',dataset=request.dataset,schema=request.schema,
                    instrument_id=identifier,raw_symbol=info['raw_symbol'],source_ts_event_ns=int(row['ts_event']),
                    request_id=request_id,coverage_evidence=assessment.evidence,published=True)
        if observation:
            fields.update(open_interest=observation['quantity'] if observation['state']!='DELETED' else None,
                          open_interest_available_at=observation['available_at'],open_interest_state=observation['state'])
        traded[key]=Bar(stamp,*(fixed_price(row[name]) for name in ('open','high','low','close')),
                        float(row['volume']),info['contract'],'NQ',**fields)
        # NOTE (QUA-24 H2): in-memory normalization NEVER mints verified OI.
        # Caller-supplied record lists are not hash-checked artifacts, so the
        # capture-bound fields above remain declarations only. Verified OI is
        # attached solely by load_capture_verified_bars / normalize_download
        # after raw file hashes are checked against a pinned manifest hash.
        if traded[key].volume<=0:
            raise ValueError('Published Databento OHLCV must contain a positive trade volume')
    output=[]
    missing=[]
    states={'TRADED':0,'NO_TRADE':0,'NO_TRADE_UNPRICED':0,'UNKNOWN':0}
    last_prices={}
    stamp=request.start
    while stamp<request.end:
        if calendar.valid_bar(stamp,timedelta(minutes=1)):
            for initial_item in ordered:
                contract=initial_item['contract']
                info=index.at(initial_item['instrument_id'],stamp)
                if info is None:
                    continue  # not listed/expired is not a no-trade interval
                bar=traded.get((stamp,contract))
                if bar:
                    output.append(bar)
                    last_prices[contract]=bar.close
                    states['TRADED']+=1
                    continue
                assessment=coverage.at(stamp)
                state='NO_TRADE' if assessment.state=='PROVIDER_AVAILABLE' else 'UNKNOWN'
                if state=='NO_TRADE' and contract not in last_prices:
                    state='NO_TRADE_UNPRICED'
                states[state]+=1
                missing.append(dict(timestamp=stamp.isoformat(),contract=contract,state=state,evidence=assessment.evidence))
                if state=='NO_TRADE' and no_trade_policy=='materialize':
                    price=last_prices[contract]
                    observation=oi.at(info['instrument_id'],stamp)
                    materialized=Bar(stamp,price,price,price,price,0,contract,'NQ',bar_state='NO_TRADE',
                        coverage_state='PROVIDER_AVAILABLE',provider='Databento',dataset=request.dataset,schema=request.schema,
                        instrument_id=info['instrument_id'],raw_symbol=info['raw_symbol'],request_id=request_id,
                        coverage_evidence=assessment.evidence+'; explicit previous-traded-price grid materialization',published=False,
                        open_interest=observation['quantity'] if observation and observation['state']!='DELETED' else None,
                        open_interest_available_at=observation['available_at'] if observation else None,
                        open_interest_state=observation['state'] if observation else None)
                    output.append(materialized)
        stamp+=timedelta(minutes=1)
    output.sort(key=lambda b:(b.timestamp,b.contract))
    if not output:
        raise ValueError('No eligible traded NQ bars in requested nearby constituents')
    integrity=validate(output,calendar)
    catalog=[dict(item) for item in ordered]
    # Use only metadata known at the start for the execution configuration, not final definitions.
    for item in catalog:
        item['expiration_date']=item['expiration'].astimezone(NY).date().isoformat()
    audit=dict(normalizer_version=NORMALIZER_VERSION,request=request.kwargs(),request_id=request_id,
               no_trade_policy=no_trade_policy,oi_policy=oi_policy,nearby_contracts=nearby_contracts,
               states=states,raw_ohlcv_records=raw_count,excluded_non_nearby_or_non_outright=discarded,
               source_out_of_order_records=source_reordering,contracts=catalog,
               definitions=index.records,open_interest_observations=oi.records,missing=missing,
               integrity=asdict(integrity),calendar=calendar.provenance(),
               warning='Available-day coverage is provider evidence, not minute-level independent completeness proof')
    return tuple(output),audit


def write_normalized(directory,bars,audit,manifest,raw_directory):
    import csv
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    fields=['timestamp','open','high','low','close','volume','contract','symbol','bar_state','coverage_state',
            'provider','dataset','schema','instrument_id','raw_symbol','source_ts_event_ns','request_id','coverage_evidence',
            'published','open_interest','open_interest_available_at','open_interest_state']
    path=directory/'bars.csv'
    with path.open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fields)
        writer.writeheader()
        for bar in bars:
            row={name:getattr(bar,name) for name in fields}
            for key in ('timestamp','open_interest_available_at'):
                if row[key] is not None:
                    row[key]=row[key].isoformat()
            writer.writerow(row)
    hashes=dict(manifest['files'])
    payload=dict(audit,provider='Databento',dataset=DATASET,schema='ohlcv-1m',
                 download_timestamp=manifest['download_timestamp'],source_hashes=hashes,
                 raw_directory=str(Path(raw_directory).resolve()),
                 raw_manifest_sha256=hash_file(Path(raw_directory)/'manifest.json'),normalized_sha256=hash_file(path),download_complete=True)
    json_write(directory/'metadata.json',payload)
    expirations={item['contract']:item['expiration_date'] for item in audit['contracts']}
    config=dict(calendar=dict(template='equity',breaks=[],overrides=audit['calendar']['document']['dates'],
                              source='Dated calendar '+audit['calendar']['document']['version']),
                data_source='Databento GLBX.MDP3 constituent OHLCV; source hashes in metadata.json',input_price_basis='raw',
                roll=dict(policy='volume',initial_contract=audit['contracts'][0]['contract'],expirations=expirations,
                          adjustment='forward_additive',position_policy='flatten',defer_until_traded_pair=True))
    json_write(directory/'research-config.json',config)
    return payload


def _check_raw_manifest(raw_directory, expected_manifest_sha256=None, _test_registry=None, require_registry=False):
    manifest=json.loads((raw_directory/'manifest.json').read_text())
    actual=hash_file(raw_directory/'manifest.json')
    if expected_manifest_sha256 is not None:
        if not isinstance(expected_manifest_sha256,str) or len(expected_manifest_sha256)!=64 \
                or actual!=expected_manifest_sha256:
            raise ValueError('Raw manifest hash does not match the independently pinned hash')
    if require_registry:
        from ..evidence_registry import resolve_registry
        if not resolve_registry(_test_registry).capture_approved(actual, provider='Databento', dataset=manifest.get('request',{}).get('dataset') if isinstance(manifest.get('request'),dict) else None):
            raise ValueError('Capture manifest is not in the approved evidence registry; a caller-supplied hash cannot authorize causal OI')
    if not manifest.get('download_complete'):
        raise ValueError('Raw request is incomplete; normalization refused')
    if not {'definition.jsonl','ohlcv-1m.jsonl'}.issubset(manifest['files']):
        raise ValueError('Raw manifest lacks required schema hashes')
    for name,digest in manifest['files'].items():
        if Path(name).name!=name or hash_file(raw_directory/name)!=digest:
            raise ValueError('Raw source hash mismatch')
    return manifest


def load_capture_verified_bars(raw_directory,calendar,*,expected_manifest_sha256=None,no_trade_policy='preserve',nearby_contracts=3,_test_registry=None):
    """Genuine Databento capture-time positive path (QUA-24).

    Re-derives OI from the hash-checked ``statistics.jsonl`` raw artifact
    and the request manifest in ``raw_directory``. Production authorization
    comes only from the approved evidence registry
    (``config/approved_evidence.json``): the manifest hash must already be
    approved there. ``expected_manifest_sha256`` is a consistency check
    only -- a caller-supplied matching hash cannot authorize fabricated
    artifacts. ``_test_registry`` is synthetic plumbing only. Each bar's
    verified OI is bound to provider/dataset/request/instrument/contract,
    the exact bar timestamp and bar event timestamp, the re-derived
    quantity, and capture time (later of OI event/receipt). Bars without
    a capture-bound observation stay unverified; replaying a verified bar
    across contracts or events is rejected by ``Bar`` and by
    ``rolls.causal_open_interest`` (which rechecks the registry).
    """
    raw_directory=Path(raw_directory)
    manifest=_check_raw_manifest(raw_directory,expected_manifest_sha256,_test_registry=_test_registry,require_registry=True)
    if 'statistics.jsonl' not in manifest['files']:
        raise ValueError('Capture-time OI requires a hashed statistics artifact in the raw manifest')
    params=manifest['request']
    request=DownloadRequest(params['start'],params['end'],params['dataset'],params['schema'],tuple(params['symbols']),params['stype_in'],schemas=tuple(manifest.get('schemas',('ohlcv-1m','definition','statistics'))))
    coverage=ProviderCoverage(request.start,request.end,manifest['conditions'],True)
    records=read_jsonl(raw_directory/'ohlcv-1m.jsonl')
    definitions=read_jsonl(raw_directory/'definition.jsonl')
    statistics=read_jsonl(raw_directory/'statistics.jsonl')
    bars,audit=normalize_records(records,definitions,statistics,request,coverage,calendar,no_trade_policy,nearby_contracts,'capture-time')
    oi=OpenInterestIndex(statistics,'capture-time')
    index=DefinitionIndex(definitions)
    manifest_sha=hash_file(raw_directory/'manifest.json')
    artifact_sha=manifest['files']['statistics.jsonl']
    verified=[]
    for bar in bars:
        observation=oi.at(bar.instrument_id,bar.timestamp) if bar.instrument_id is not None else None
        if observation is None or observation['quantity'] is None or bar.open_interest is None:
            verified.append(bar); continue
        info=index.at(bar.instrument_id,bar.timestamp)
        if info is None or info['contract']!=bar.contract or observation['quantity']!=bar.open_interest:
            raise ValueError('Re-derived capture OI does not bind to this bar contract/quantity')
        verified.append(_mint_verified_open_interest(
            bar,oi_source_ts_event_ns=observation['source_ts_event_ns'],
            oi_source_ts_recv_ns=observation['source_ts_recv_ns'],
            capture_manifest_sha256=manifest_sha,capture_artifact_sha256=artifact_sha,
            receipt_id=f"databento-capture:{bar.request_id}:{bar.instrument_id}:{observation['source_ts_recv_ns']}"))
    return tuple(verified),audit


def normalize_download(raw_directory,directory,calendar,no_trade_policy='preserve',nearby_contracts=3,oi_policy='retrospective',expected_manifest_sha256=None,_test_registry=None):
    raw_directory=Path(raw_directory)
    # Capture-time authorization is the approved evidence registry check
    # inside _check_raw_manifest, not a caller-supplied hash.
    manifest=_check_raw_manifest(raw_directory,expected_manifest_sha256,_test_registry=_test_registry,require_registry=(oi_policy=='capture-time'))
    params=manifest['request']
    request=DownloadRequest(params['start'],params['end'],params['dataset'],params['schema'],tuple(params['symbols']),params['stype_in'],schemas=tuple(manifest.get('schemas',('ohlcv-1m','definition','statistics'))))
    coverage=ProviderCoverage(request.start,request.end,manifest['conditions'],True)
    records=read_jsonl(raw_directory/'ohlcv-1m.jsonl')
    definitions=read_jsonl(raw_directory/'definition.jsonl')
    statistics=read_jsonl(raw_directory/'statistics.jsonl') if (raw_directory/'statistics.jsonl').exists() else []
    bars,audit=normalize_records(records,definitions,statistics,request,coverage,calendar,no_trade_policy,nearby_contracts,oi_policy)
    return write_normalized(directory,bars,audit,manifest,raw_directory)


class DatabentoProvider(DataProvider):
    """Load normalized historical files without importing the Databento SDK."""
    def __init__(self,path,calendar=None):
        self.path=Path(path)
        self.metadata=json.loads((self.path.parent/'metadata.json').read_text())
        self.calendar=calendar or DatedSessionCalendar(self.metadata['calendar']['document'])
        if not self.metadata.get('download_complete') or self.metadata.get('provider')!='Databento':
            raise ValueError('Not a complete Databento normalization')
        if calendar is not None and calendar.provenance()['document_sha256'] != self.metadata['calendar']['document_sha256']:
            raise ValueError('Calendar provenance mismatch')
        if self.calendar.provenance()['document_sha256'] != self.metadata['calendar']['document_sha256']:
            raise ValueError('Calendar document hash mismatch')
        self.sidecar_sha256=hash_file(self.path.parent/'metadata.json')
        raw=Path(self.metadata['raw_directory'])
        if hash_file(raw/'manifest.json') != self.metadata['raw_manifest_sha256']:
            raise ValueError('Raw manifest hash mismatch')
        for name,digest in self.metadata['source_hashes'].items():
            if Path(name).name != name or hash_file(raw/name) != digest:
                raise ValueError('Raw source hash mismatch')
        if hash_file(self.path)!=self.metadata['normalized_sha256']:
            raise ValueError('Normalized data hash mismatch')

    def load(self):
        bars,report=CSVProvider(self.path,'NQ',self.calendar).load()
        report.warnings.append('Provider missing-state counts: '+json.dumps(self.metadata['states'],sort_keys=True))
        return bars,report
