"use client";
import {useEffect,useState} from 'react';
import {type IChartApi,type ISeriesApi,type UTCTimestamp} from 'lightweight-charts';
import type {Snapshot} from '@/lib/types';
// Explicit boundary layer shares the chart's time-coordinate transform. It
// carries no invented price points and does not alter candle or volume data.
export default function ContinuousOverlay({chart,data,host}:{chart:IChartApi;series:ISeriesApi<'Candlestick'>;data:Snapshot|null;host:HTMLDivElement|null}){
  const [,refresh]=useState(0);
  useEffect(()=>{
    if(!data?.continuous || !host)return;
    const update=()=>refresh(n=>n+1);
    chart.timeScale().subscribeVisibleLogicalRangeChange(update);
    const observer=new ResizeObserver(update);observer.observe(host);
    const frame=requestAnimationFrame(update);
    return()=>{chart.timeScale().unsubscribeVisibleLogicalRangeChange(update);observer.disconnect();cancelAnimationFrame(frame);};
  },[chart,data,host]);
  if(!data?.continuous||!host)return null;
  let previousLabel=-100;
  const range=chart.timeScale().getVisibleLogicalRange();
  const labelsEnabled=!!range && range.to-range.from<500;
  const width=host.clientWidth,height=host.clientHeight;
  return <svg className="continuous-boundaries" width={width} height={height} style={{top:host.offsetTop}} aria-label="Contract rollover boundaries">
    {data.continuous.rolls.map(roll=>{
      const bar=data.bars.find(b=>b.source_contract===roll.new_contract && (b.trading_date||'')>=roll.trading_date);
      if(!bar||Date.parse(roll.decision_utc)>Date.parse(data.as_of))return null;
      const x=chart.timeScale().timeToCoordinate(bar.time as UTCTimestamp);
      if(x===null||x<0||x>width-60)return null;
      const unresolved=roll.overlap?.status==='unresolved';
      const label=labelsEnabled&&x-previousLabel>100;if(label)previousLabel=x;
      return <g key={roll.roll_id} className="roll-marker" data-testid="roll-marker" transform={`translate(${x},0)`}>
        <title>{roll.trading_date}: {roll.old_contract} → {roll.new_contract}; {unresolved?'overlap unresolved; independent adjustment block':roll.overlap?.status||'calendar-only transition'}</title>
        <line y1={labelsEnabled?18:0} y2={height} stroke={unresolved?'#ef6c7c':'#deb568'} strokeOpacity={unresolved?.32:.14} strokeDasharray="2 6" />
        <rect x={-4} width={8} height={18} fill="transparent" />
        {label&&<text x={5} y={11} fill={unresolved?'#ef6c7c':'#deb568'} fontSize={10}>{roll.new_contract}</text>}
      </g>;
    })}
  </svg>;
}
