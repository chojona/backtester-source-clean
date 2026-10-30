"""Cost-gated historical acquisition, offline normalization and manual audit output."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
from math import isfinite
from .providers.databento import (DownloadRequest, HistoricalGateway, MissingAPIKey,
    DatabentoProvider, normalize_download, redacted, read_jsonl, flat_record, ns_time, fixed_price)
from .providers.coverage import DatedSessionCalendar


def inspect_provider(path, config_path, count=8):
    """Compare selected traded bars directly with retained raw records and causal features."""
    from .rolls import ContinuousSeries, RollConfig
    from .features import FeatureEngine
    provider=DatabentoProvider(path)
    bars,_=provider.load()
    config=json.loads(Path(config_path).read_text())
    series=ContinuousSeries(provider.calendar,RollConfig(**config['roll']))
    selected=tuple(series.select(bars))
    raw_dir=Path(provider.metadata['raw_directory'])
    from .providers.databento import hash_file
    for name,digest in provider.metadata['source_hashes'].items():
        if Path(name).name!=name or hash_file(raw_dir/name)!=digest:
            raise ValueError('Raw source hash mismatch during audit')
    source={(int(r['instrument_id']),int(r['ts_event'])):r for r in read_jsonl(raw_dir/'ohlcv-1m.jsonl')}
    traded=[i for i,item in enumerate(selected) if item.raw.bar_state=='TRADED']
    if not traded:
        raise ValueError('No traded bars available for manual inspection')
    indexes={traded[round(i*(len(traded)-1)/max(count-1,1))] for i in range(count)}
    indexes.update(i for i,item in enumerate(selected) if item.roll)
    features=FeatureEngine(provider.calendar,**config.get('features',{}))
    samples=[]
    previous=None
    for i,item in enumerate(selected):
        current=features.update(item.research,reset=bool(item.roll and item.roll.adjustment=='unadjusted_reset'))
        if i in indexes:
            row=source[(item.raw.instrument_id,item.raw.source_ts_event_ns)]
            fields=('open','high','low','close')
            matches=all(getattr(item.raw,f)==fixed_price(row[f]) for f in fields) and item.raw.volume==int(row['volume'])
            if not matches:
                raise ValueError('Normalized OHLCV differs from retained raw record')
            info=provider.calendar.classify(item.raw.timestamp)
            samples.append(dict(timestamp=item.raw.timestamp.isoformat(),ts_event_ns=item.raw.source_ts_event_ns,
                raw_symbol=item.raw.raw_symbol,contract=item.raw.contract,instrument_id=item.raw.instrument_id,
                raw_ohlcv={f:getattr(item.raw,f) for f in (*fields,'volume')},matches_retained_raw=True,
                session=info.session,trading_date=info.trading_date.isoformat(),
                weekly_vwap=current['weekly_vwap'],previous_completed_bar_weekly_vwap=previous['weekly_vwap'] if previous else None,
                weekly_vwap_complete=current['weekly_vwap_complete'],active_contract=item.raw.contract,
                roll=item.roll.__dict__ if item.roll else None))
        previous=current
    return dict(status='READY_FOR_HUMAN_REVIEW',samples=samples,rolls=[r.__dict__ for r in series.records],
                note='Raw-file comparison and feature audit; not independent exchange confirmation or completed human review')


def main():
    parser=argparse.ArgumentParser(description='Databento NQ historical acquisition; UTC range end is exclusive')
    sub=parser.add_subparsers(dest='command',required=True)
    download=sub.add_parser('download')
    download.add_argument('--provider',choices=['databento'],default='databento')
    download.add_argument('--symbol',choices=['NQ'],default='NQ')
    download.add_argument('--schema',choices=['ohlcv-1m'],default='ohlcv-1m')
    download.add_argument('--start',required=True)
    download.add_argument('--end',required=True)
    download.add_argument('--output',type=Path,default=Path('data'))
    download.add_argument('--estimate-only',action='store_true')
    download.add_argument('--max-cost-usd',type=float,help='Explicit total estimate ceiling; required for any billed download')
    download.add_argument('--allow-large-range',action='store_true',help='Explicitly permit a range longer than 16 calendar days')
    download.add_argument('--calendar',type=Path)
    normalize=sub.add_parser('normalize')
    normalize.add_argument('raw_directory',type=Path)
    normalize.add_argument('--output',type=Path,required=True)
    normalize.add_argument('--calendar',type=Path,required=True)
    for command in (download,normalize):
        command.add_argument('--no-trade-policy',choices=['preserve','materialize'],default='preserve')
        command.add_argument('--nearby-contracts',type=int,default=3)
        command.add_argument('--oi-policy',choices=['retrospective','capture-time'],default='retrospective')
    inspect=sub.add_parser('inspect-provider')
    inspect.add_argument('data',type=Path)
    inspect.add_argument('--config',type=Path,required=True)
    inspect.add_argument('--samples',type=int,default=8)
    args=parser.parse_args()
    try:
        if args.command=='inspect-provider':
            if not 2<=args.samples<=100:
                raise ValueError('Use 2–100 inspection samples')
            print(json.dumps(inspect_provider(args.data,args.config,args.samples),indent=2,default=str))
            return
        if args.command=='normalize':
            payload=normalize_download(args.raw_directory,args.output,DatedSessionCalendar.from_file(args.calendar),
                args.no_trade_policy,args.nearby_contracts,args.oi_policy)
            print(json.dumps(dict(output=str(args.output.resolve()),states=payload['states'],sha256=payload['normalized_sha256']),indent=2))
            return
        request=DownloadRequest(args.start,args.end,schema=args.schema,symbol=args.symbol)
        if args.max_cost_usd is not None and (not isfinite(args.max_cost_usd) or args.max_cost_usd<0):
            raise ValueError('Cost ceiling must be finite and nonnegative')
        gateway=HistoricalGateway()
        estimate=gateway.estimate(request)
        print(json.dumps(estimate,indent=2))
        if args.estimate_only:
            return
        if args.max_cost_usd is None:
            raise ValueError('Estimate shown; specify --max-cost-usd to authorize a bounded download')
        if estimate['total_cost_usd']>args.max_cost_usd:
            raise ValueError('Estimate exceeds authorized ceiling; no time-series download made')
        if (request.end-request.start).days>16 and not args.allow_large_range:
            raise ValueError('Start with 5–10 trading days; larger requests require --allow-large-range and a cost ceiling')
        if not args.calendar:
            raise ValueError('A dated --calendar is required before any billed download')
        calendar=DatedSessionCalendar.from_file(args.calendar)
        calendar.verify_range(request.start,request.end)
        metadata=gateway.metadata(request)
        identifier=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        raw=args.output/'raw'/'databento'/'NQ'/identifier
        normalized=args.output/'normalized'/'databento'/'NQ'/identifier
        gateway.download(request,raw,estimate,metadata)
        payload=normalize_download(raw,normalized,calendar,args.no_trade_policy,args.nearby_contracts,args.oi_policy)
        print(json.dumps(dict(raw=str(raw.resolve()),normalized=str(normalized.resolve()),states=payload['states']),indent=2))
    except MissingAPIKey:
        print('SKIPPED: DATABENTO_API_KEY is not set. No network request or download made.')
    except (ValueError,RuntimeError,TypeError,OSError,KeyError) as error:
        parser.error(redacted(str(error)))


if __name__=='__main__':
    main()
