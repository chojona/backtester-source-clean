import type {Bar} from './types';
// Whitespace is a display gap, never a candle or an interpolated price.
export function indicatorPoints(bars:Bar[],field:'vwap'|'or_high'|'or_low'|'vwap_upper'|'vwap_lower',continuous:boolean){
  const points:({time:number;value:number}|{time:number})[]=[];
  let previous:Bar|undefined;
  for(const bar of bars){
    if(continuous && previous && (bar.source_contract!==previous.source_contract || bar.trading_date!==previous.trading_date || bar.time>previous.available_at)){
      if(bar.time>previous.time+1)points.push({time:previous.time+1});
      else {points.push({time:bar.time});previous=bar;continue;}
    }
    if(bar[field]!==null)points.push({time:bar.time,value:bar[field]!});
    previous=bar;
  }
  return points;
}
