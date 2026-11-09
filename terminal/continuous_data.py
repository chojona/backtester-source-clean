"""Read-only chart view over verified continuous artifacts, never an engine input."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path

import duckdb

from .continuous import SYMBOLS, VERSION, literal, identity
from .data import DataError, digest, ET, FRAMES


class ContinuousStore:
    def __init__(self, root, original):
        self.root, self.original = Path(root).resolve(), original
        self.manifest = json.loads((self.root/'SUCCESS.json').read_text())
        if self.manifest['version'] != VERSION or identity(self.manifest['specification']) != self.manifest['build_id']:
            raise DataError('Invalid continuous artifact version or identity')
        outputs = self.manifest['outputs']
        required = {*SYMBOLS.values(), 'session-eligibility.parquet', 'selected-gap-intervals.parquet',
                    'rollover-manifest.json', 'adjustment-manifest.json', 'quality-report.json'}
        if missing := required.difference(outputs):
            raise DataError(f'Continuous seal is missing output hashes: {", ".join(sorted(missing))}')
        for name, expected in outputs.items():
            if Path(name).name != name or digest(self.root/name) != expected:
                raise DataError('Changed continuous artifact: '+name)
        inputs = self.manifest['specification']['inputs']
        for name in ('summary.json','session-eligibility.parquet','selected-observations-with-flags.parquet','contract-rolls.parquet'):
            if inputs[name] != original.hashes[name]:
                raise DataError('Continuous artifact belongs to a different source release')
        for name in ('session-eligibility.parquet', 'selected-gap-intervals.parquet'):
            if outputs[name] != inputs[name]:
                raise DataError('Copied continuous metadata differs from its bound source: '+name)
        self.rolls = json.loads((self.root/'rollover-manifest.json').read_text())['rolls']
        self.quality = json.loads((self.root/'quality-report.json').read_text())

    def query(self, symbol, sql, params=()):
        if symbol not in SYMBOLS:
            raise DataError('Unknown continuous symbol')
        with duckdb.connect(':memory:') as con:
            con.execute("SET TimeZone='UTC'")
            for view,name in [('bars',SYMBOLS[symbol]),('sessions','session-eligibility.parquet'),('gaps','selected-gap-intervals.parquet')]:
                con.execute(f'CREATE VIEW {view} AS SELECT * FROM read_parquet({literal(self.root/name)})')
            result=con.execute(sql,params)
            names=[d[0] for d in result.description]
            return [dict(zip(names,row)) for row in result.fetchall()]

    def contracts(self):
        stats=self.query('NQ1! Raw','SELECT min(trading_date) AS first_session,max(trading_date) AS last_session,count(*) AS sessions FROM sessions')[0]
        return [dict(stats,contract=symbol,label=symbol) for symbol in SYMBOLS]

    def sessions(self,symbol,start,end,limit,offset):
        return self.query(symbol,'''SELECT trading_date,? AS contract,selected_contract AS source_contract,
            observed_minutes AS minutes,prior_candidate_date,calendar_status,certified_complete,roll,warmup_14_ready,
            eligible_full_session,quality_flags,absent_candidate_minutes
            FROM sessions WHERE (? IS NULL OR trading_date>=?) AND (? IS NULL OR trading_date<=?)
            ORDER BY trading_date DESC LIMIT ? OFFSET ?''',
            [symbol,str(start) if start else None,str(start) if start else None,str(end) if end else None,str(end) if end else None,limit,offset])

    def intraday_window(self, symbol, anchor, direction, timeframe, display,
                        opening_minutes, deviations, limit):
        # Page by declared sessions so gaps and empty sessions never stall a pan.
        comparison, order = ('<', 'DESC') if direction == 'older' else ('>', 'ASC')
        dates = self.query(symbol, f'''SELECT trading_date FROM sessions
            WHERE trading_date {comparison} ? ORDER BY trading_date {order} LIMIT ?''',
            [anchor.isoformat(), limit])
        page = {'contract': symbol, 'build_id': self.manifest['build_id'],
                'timeframe': timeframe, 'display': display,
                'session_dates': [], 'bars': [], 'gaps': [], 'rolls': [], 'as_of': None,
                'at_edge': len(dates) < limit}
        if dates:
            end = date.fromisoformat(max(row['trading_date'] for row in dates))
            snapshot = self.snapshot(symbol, end, timeframe, display=display,
                                     opening_minutes=opening_minutes, deviations=deviations,
                                     history_sessions=len(dates))
            page.update(bars=snapshot['bars'], as_of=snapshot['as_of'])
            for field in ('session_dates', 'gaps', 'rolls'):
                page[field] = snapshot['continuous'][field]
        return page

    def snapshot(self,symbol,session,timeframe='1m',cursor=None,as_of=None,offset=0,limit=50,
                 display='Globex',opening_minutes=30,deviations=1,history_sessions=1):
        adjusted=symbol=='NQ1! Adjusted'
        if adjusted and (cursor is not None or as_of is not None):
            raise DataError('Retrospective adjusted prices are unavailable in replay/as_of. Select NQ1! Raw.')
        if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
            raise DataError('as_of must include a timezone')
        if timeframe not in FRAMES or display not in ('Globex','RTH') or not 1<=opening_minutes<=120 or not .25<=deviations<=5:
            raise DataError('Invalid chart configuration')
        if not 1<=history_sessions<=5000:
            raise DataError('Invalid history length')
        if (cursor is not None or as_of is not None) and history_sessions!=1:
            raise DataError('Replay is limited to one selected session; navigate to the next session to cross a roll')
        chosen=self.sessions(symbol,None,session,history_sessions,0)
        if not chosen or chosen[0]['trading_date']!=session.isoformat():
            raise DataError('Unknown continuous trading date')
        first=chosen[-1]['trading_date']
        bounds=self.query(symbol,'''SELECT count(*) AS total,min(timestamp_utc) AS first,max(timestamp_utc) AS last
            FROM bars WHERE trading_date=?''',[session.isoformat()])[0]
        total=bounds['total']
        if cursor is not None and not 0<=cursor<=total:
            raise DataError('cursor outside session')
        # Missing sessions have no artificial candles or fabricated session bounds.
        end_of_day=datetime.combine(session+timedelta(days=1),datetime.min.time(),ET)
        gap_end=self.query(symbol,'SELECT max(end_exclusive_utc) AS last FROM gaps WHERE trading_date=?',[session.isoformat()])[0]['last']
        observed_end=bounds['last']+timedelta(minutes=1) if total else None
        reviewed_end=max(x for x in (gap_end,observed_end) if x is not None) if gap_end is not None or observed_end is not None else end_of_day
        cutoff=as_of or reviewed_end
        where='trading_date>=? AND trading_date<=? AND CAST(timestamp_utc AS TIMESTAMPTZ)+INTERVAL 1 MINUTE<=?'
        params=[first,session.isoformat(),cutoff]
        if cursor is not None:
            rows=self.query(symbol,f'''SELECT timestamp_utc FROM bars WHERE {where} ORDER BY timestamp_utc LIMIT ?''',params+[cursor])
            cutoff=rows[-1]['timestamp_utc']+timedelta(minutes=1) if rows else min(cutoff,bounds['first']) if total else cutoff
            params[-1]=cutoff
        available=self.query(symbol,f'SELECT count(*) AS n FROM bars WHERE {where}',params)[0]['n']
        if timeframe!='daily' and available>200000:
            raise DataError('Intraday view limited to 200,000 source observations; shorten history or choose D')
        if timeframe=='daily':
            # Aggregate source minutes in DuckDB, never load millions of bars into the browser.
            rows=self.query(symbol,f'''SELECT trading_date,source_contract,segment_id,roll_id,
                min(timestamp_utc) AS timestamp_utc,max(timestamp_utc) AS last_timestamp,
                arg_min(open,timestamp_utc) AS open,max(high) AS high,min(low) AS low,arg_max(close,timestamp_utc) AS close,
                sum(volume) AS volume,count(*) AS source_count,first(adjustment_offset) AS adjustment_offset,
                first(adjustment_status) AS adjustment_status,first({"adjustment_block_id" if adjusted else "segment_id"}) AS adjustment_block_id,bool_and(eligible_full_session) AS eligible_full_session,
                arg_min(raw_open,timestamp_utc) AS raw_open,max(raw_high) AS raw_high,min(raw_low) AS raw_low,arg_max(raw_close,timestamp_utc) AS raw_close,
                sum((high+low+close)/3*volume)/nullif(sum(volume),0) AS daily_vwap
                FROM bars WHERE {where} {'AND hour(timezone(\'America/New_York\',CAST(timestamp_utc AS TIMESTAMPTZ)))*60+minute(timezone(\'America/New_York\',CAST(timestamp_utc AS TIMESTAMPTZ))) BETWEEN 570 AND 959' if display=='RTH' else ''}
                GROUP BY trading_date,source_contract,segment_id,roll_id ORDER BY timestamp_utc''',params)
        else:
            rows=self.query(symbol,f'SELECT * FROM bars WHERE {where} ORDER BY timestamp_utc',params)
        candles,buckets=[],{}
        previous_key=None
        pv=vol=0.0
        mean=m2=0.0
        or_high=or_low=None
        span=FRAMES[timeframe]*60
        unresolved=0
        for row in rows:
            key=(row['trading_date'],row['source_contract'],row['segment_id'])
            stamp=row['timestamp_utc']
            if key!=previous_key:
                pv=vol=mean=m2=0.0
                or_high=or_low=None
                anchor=int(stamp.timestamp())
                previous_key=key
            if row['open'] is None:
                unresolved+=row.get('source_count',1)
                continue
            local=stamp.astimezone(ET)
            minute=local.hour*60+local.minute
            if display=='RTH' and timeframe!='daily' and not 570<=minute<960:
                continue
            if timeframe=='daily':
                bucket=int(stamp.timestamp())
                vwap=row['daily_vwap'];sd=None
            else:
                typical=(row['high']+row['low']+row['close'])/3
                pv+=typical*row['volume'];newvol=vol+row['volume']
                if row['volume']>0:
                    delta=typical-mean;mean+=row['volume']/newvol*delta;m2+=row['volume']*delta*(typical-mean)
                vol=newvol;vwap=pv/vol if vol else None;sd=math.sqrt(max(0,m2/vol)) if vol else None
                if 570<=minute<570+opening_minutes:
                    or_high=max(or_high,row['high']) if or_high is not None else row['high']
                    or_low=min(or_low,row['low']) if or_low is not None else row['low']
                bucket=anchor+((int(stamp.timestamp())-anchor)//span)*span
            bkey=(key,bucket)
            if bkey not in buckets:
                buckets[bkey]={'time':bucket,'open':row['open'],'high':row['high'],'low':row['low'],'close':row['close'],
                    'volume':0,'source_count':0,'source_contract':row['source_contract'],'roll_id':row['roll_id'],
                    'segment_id':row['segment_id'],'adjustment_block_id':row.get('adjustment_block_id') if adjusted else None,'adjustment_offset':row['adjustment_offset'],
                    'adjustment_status':row['adjustment_status'],'retrospective':adjusted,
                    'eligible_full_session':row['eligible_full_session'],'trading_date':row['trading_date'],
                    'raw_open':row['raw_open'],'raw_high':row['raw_high'],'raw_low':row['raw_low'],'raw_close':row['raw_close']}
            b=buckets[bkey]
            available_at=int((row.get('last_timestamp') or stamp).timestamp())+60
            b.update(high=max(b['high'],row['high']),low=min(b['low'],row['low']),close=row['close'],
                volume=b['volume']+row['volume'],source_count=b['source_count']+row.get('source_count',1),
                raw_high=max(b['raw_high'],row['raw_high']),raw_low=min(b['raw_low'],row['raw_low']),raw_close=row['raw_close'],
                available_at=available_at,vwap=vwap,vwap_upper=vwap+deviations*sd if sd is not None and vwap is not None else None,
                vwap_lower=vwap-deviations*sd if sd is not None and vwap is not None else None,
                or_high=or_high,or_low=or_low,partial=available_at<bucket+span and (cursor is not None or as_of is not None))
        candles=list(buckets.values())
        gaps=self.query(symbol,'''SELECT trading_date,contract,start_utc,end_exclusive_utc,minutes,classification
            FROM gaps WHERE trading_date>=? AND trading_date<=? AND CAST(start_utc AS TIMESTAMPTZ)<? ORDER BY start_utc LIMIT 2000''',
            [first,session.isoformat(),cutoff])
        gap_count=self.query(symbol,'SELECT count(*) AS n FROM gaps WHERE trading_date>=? AND trading_date<=? AND CAST(start_utc AS TIMESTAMPTZ)<?',[first,session.isoformat(),cutoff])[0]['n']
        for gap in gaps:
            gap['start_utc']=gap['start_utc'].isoformat()
            gap['end_exclusive_utc']=min(gap['end_exclusive_utc'],cutoff).isoformat()
            gap['minutes']=int((datetime.fromisoformat(gap['end_exclusive_utc'])-datetime.fromisoformat(gap['start_utc'])).total_seconds()/60)
        transitions=[r for r in self.rolls if first<=r['trading_date']<=session.isoformat() and datetime.fromisoformat(r['decision_utc'])<=cutoff]
        if cursor is not None or as_of is not None:
            # No future historical overlap references or backward offsets in raw replay.
            transitions=[{k:r[k] for k in ('roll_id','trading_date','decision_utc','old_contract','new_contract','policy_version')} for r in transitions]
        latest=[b for b in candles if b['trading_date']==session.isoformat()]
        last=latest[-1] if latest else None
        stats={k:None for k in ('open','high','low','close','volume','vwap','realized_volatility','or_high','or_low','or_complete','or_range','range','vwap_deviation')}
        if latest:
            stats.update(open=latest[0]['open'],high=max(b['high'] for b in latest),low=min(b['low'] for b in latest),
                close=last['close'],volume=sum(b['volume'] for b in latest),vwap=last['vwap'],or_high=last['or_high'],or_low=last['or_low'])
            stats['range']=stats['high']-stats['low'];stats['vwap_deviation']=last['close']-last['vwap'] if last['vwap'] else None
        return {'contract':symbol,'session':session.isoformat(),'timeframe':timeframe,'display':display,
            'bars':candles,'stats':stats,'previous':{'high':None,'low':None,'date':None},
            'cursor':min(cursor,available) if cursor is not None else available if history_sessions==1 else total,'total_minutes':total,
            'as_of':cutoff.isoformat(),'session_start':bounds['first'].isoformat() if total else cutoff.isoformat(),
            'session_end':(bounds['last']+timedelta(minutes=1)).isoformat() if total else cutoff.isoformat(),
            'boundaries':[],'opening_minutes':opening_minutes,'deviations':deviations,
            'explorer':{'rows':candles[offset:offset+limit],'total':len(candles),'offset':offset,'limit':limit},
            'eligibility':{'eligible_full_session':chosen[0]['eligible_full_session'],'strict_eligible':False,
                'calendar_status':chosen[0]['calendar_status'],'roll':chosen[0]['roll'],'warmup_14_ready':chosen[0]['warmup_14_ready']},
            'continuous':{'version':VERSION,'build_id':self.manifest['build_id'],'retrospective':adjusted,
                'source_contract':chosen[0]['source_contract'],'history_sessions':len(chosen),
                'session_dates':[s['trading_date'] for s in reversed(chosen)],'rolls':transitions,
                'gaps':gaps,'gap_count':gap_count,'gaps_truncated':gap_count>len(gaps),'ineligible_sessions':[{k:s[k] for k in ('trading_date','quality_flags','absent_candidate_minutes')} for s in chosen if not s['eligible_full_session']],
                'unadjustable_observations':unresolved,'performance_eligible':False,
                'notice':'Retrospective additive blocks; unresolved rolls separate price anchors. Replay and strategy execution disabled.' if adjusted else 'Unadjusted observed prices; research exclusions retained. Roll jumps are not performance returns.'}}


    def cursor_at(self,symbol,session,clock):
        meta=self.snapshot(symbol,session,cursor=0)
        try:
            parsed=datetime.strptime(clock,'%H:%M').time()
        except ValueError as error:
            raise DataError('Time must be HH:MM ET') from error
        start=datetime.fromisoformat(meta['session_start'])
        target=datetime.combine(session,parsed,ET)
        if parsed.hour>=start.astimezone(ET).hour:
            target=datetime.combine(start.astimezone(ET).date(),parsed,ET)
        if not start<=target<=datetime.fromisoformat(meta['session_end']):
            raise DataError('Time outside selected session')
        return self.query(symbol,"SELECT count(*) AS n FROM bars WHERE trading_date=? AND CAST(timestamp_utc AS TIMESTAMPTZ)+INTERVAL 1 MINUTE<=?",[session.isoformat(),target])[0]['n']
