"use client";
import { useEffect, useRef, useState } from "react";
import { createSeriesMarkers, LineSeries, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import type { Snapshot } from "@/lib/types";
type Event = {bar_time:string; signal_at:string; session:string; contract:string; direction:number; classification:string; reference_close:number; outcomes?:Record<string,{outcome_at:string}>};
type Research = {contract:string; provenance?:{release_sha256?:string}; events:Event[]};
export default function ResearchOverlay({chart,series,data,replay,datasetHash}:{chart:IChartApi;series:ISeriesApi<"Candlestick">;data:Snapshot|null;replay:boolean;datasetHash?:string}) {
  const [id,setId]=useState("");
  const verifiedRelease=useRef("");
  useEffect(()=>{const receive=(e:MessageEvent)=>{if(e.origin===location.origin && e.data?.type==='nq-research-selected' && /^[0-9a-f]{64}$/.test(e.data.id))setId(e.data.id);};window.addEventListener('message',receive);return()=>window.removeEventListener('message',receive);},[]);
  useEffect(()=>{
    if(data?.continuous)return;
    const controller=new AbortController();
    const markerApi=createSeriesMarkers(series,[]);
    const windows:ISeriesApi<"Line">[]=[];
    if(id&&data&&data.timeframe==='1m'&&datasetHash){
      // Fetch a fully verified artifact for its release identity outside replay.
      // Replay never requests outcomes or full-sample metadata.
      const query=replay?'?as_of='+encodeURIComponent(data.as_of):'';
      fetch('/api/research/experiments/'+id+query,{signal:controller.signal,cache:'no-store'}).then(r=>r.json()).then((r:Research)=>{
        if(controller.signal.aborted || r.contract!==data.contract)return;
        // Replay views omit provenance by design. Exact candle/contract matching
        // below remains mandatory; full views also bind the sealed release.
        if(!replay){if(r.provenance?.release_sha256!==datasetHash)return;verifiedRelease.current=id+datasetHash;}
        if(replay&&verifiedRelease.current!==id+datasetHash)return;
        const events=r.events.filter(e=>e.contract===data.contract&&e.session===data.session&&Date.parse(e.signal_at)<=Date.parse(data.as_of)&&data.bars.some(b=>b.time===Date.parse(e.bar_time)/1000 && b.close===e.reference_close));
        markerApi.setMarkers(events.map(e=>({time:Date.parse(e.bar_time)/1000 as UTCTimestamp,position:e.direction>0?'belowBar' as const:'aboveBar' as const,color:e.direction>0?'#32bca4':'#ef6c7c',shape:e.direction>0?'arrowUp' as const:'arrowDown' as const,text:e.classification})).sort((a,b)=>a.time-b.time));
        if(!replay)for(const e of events){const end=e.outcomes?.['15']?.outcome_at;if(!end)continue;const line=chart.addSeries(LineSeries,{color:'#deb568',lineWidth:1,priceLineVisible:false,lastValueVisible:false});line.setData([{time:Date.parse(e.bar_time)/1000 as UTCTimestamp,value:e.reference_close},{time:(Date.parse(end)/1000-60) as UTCTimestamp,value:e.reference_close}]);windows.push(line);}
      }).catch(()=>{});
    }
    return()=>{controller.abort();markerApi.detach();for(const line of windows)chart.removeSeries(line);};
  },[chart,series,data,replay,id,datasetHash]);
  return null;
}
