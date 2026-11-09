"use client";
import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import type {Snapshot} from '@/lib/types';
import {api} from '@/lib/types';
type Tab='rolls'|'sessions'|'gaps';
type Gap={start_utc:string;end_exclusive_utc:string;classification:string;minutes:number};
const pageSize=20;
const count=(n:number)=>n.toLocaleString('en-US');
const dateLabel=(value:string)=>new Date(value+'T12:00:00Z').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'});
const timeLabel=(value:string)=>new Date(value).toLocaleString('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});
const reasons:Record<string,string>={ROLL_TRANSITION:'Contract rollover',SAME_CONTRACT_PRIOR_FULL_GRID_UNAVAILABLE:'Previous session incomplete',ORDINARY_GRID_ABSENCE_UNRESOLVED_OR_CLASSIFIED:'Missing or unresolved observations',SELECTED_CONTRACT_NOT_OBSERVED:'Selected contract not observed',UNRESOLVED_BOUNDARY_OBSERVATION:'Session boundary requires review'};
export default function ContinuousQuality({data}:{data:Snapshot}){
  const [open,setOpen]=useState(false),[tab,setTab]=useState<Tab>('rolls'),[page,setPage]=useState(0),[gaps,setGaps]=useState<Gap[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(false);
  const dialog=useRef<HTMLDialogElement>(null),trigger=useRef<HTMLButtonElement>(null);
  const continuous=data.continuous!;
  useEffect(()=>{if(!open)return;const element=dialog.current;element?.showModal();return()=>{element?.close();trigger.current?.focus();};},[open]);
  useEffect(()=>{if(!open||tab!=='gaps')return;const controller=new AbortController();setLoading(true);setError('');const params=new URLSearchParams({start:continuous.session_dates[0]||data.session,end:continuous.session_dates.at(-1)||data.session,as_of:data.as_of,limit:String(pageSize),offset:String(page*pageSize)});api<Gap[]>('continuous/gaps?'+params,controller.signal).then(rows=>{setGaps(rows);setLoading(false);}).catch(e=>{if(!controller.signal.aborted){setError(e.message);setLoading(false);}});return()=>controller.abort();},[open,tab,page,data]);
  const total=tab==='rolls'?continuous.rolls.length:tab==='sessions'?continuous.ineligible_sessions.length:continuous.gap_count;
  const from=page*pageSize;
  return <div className="quality-access" data-testid="continuous-quality">
    <button ref={trigger} className="quality-trigger" onClick={()=>setOpen(true)} aria-haspopup="dialog">Data quality <span aria-hidden="true">↗</span></button>
    <span className="quality-status">{continuous.gap_count ? 'Coverage gaps recorded' : 'Observed data'} · not certified</span>
    {open&&createPortal(<dialog ref={dialog} className="quality-dialog" aria-label="Continuous data quality" onCancel={()=>setOpen(false)} onClick={e=>{if(e.target===e.currentTarget)setOpen(false);}}>
      <section className="quality-dialog-content">
        <header className="quality-heading"><div><span>DATA & PROVENANCE</span><h2>Continuous data quality</h2></div><button aria-label="Close data quality" onClick={()=>setOpen(false)}>✕</button></header>
        <p className="quality-intro">{continuous.retrospective ? 'Adjusted within independently anchored blocks. Unresolved rollovers keep separate price anchors; replay is unavailable.' : 'Original observed prices across contracts. Rollover price jumps are excluded from research returns.'}</p>
        <div className="quality-stats">{[['Sessions',continuous.history_sessions],['Rollovers',continuous.rolls.length],['Missing intervals',continuous.gap_count],['Excluded sessions',continuous.ineligible_sessions.length]].map(([name,value])=><div key={String(name)}><strong>{count(Number(value))}</strong><span>{name}</span></div>)}</div>
        <p className="quality-policy">Research eligibility and historical certification are separate. Indicators reset at session and contract boundaries. Missing bars are never filled.</p>
        <div className="quality-tabs" role="tablist" aria-label="Data quality details">{(['rolls','sessions','gaps'] as Tab[]).map(key=><button key={key} role="tab" aria-selected={tab===key} onClick={()=>{setTab(key);setPage(0);}}>{key==='rolls'?'Rollovers':key==='sessions'?'Excluded sessions':'Missing intervals'}</button>)}</div>
        <div className="quality-table-scroll" aria-busy={loading}>
          {error?<p role="alert">{error}</p>:loading?<p role="status">Loading intervals…</p>:<table><thead><tr>{(tab==='rolls'?['Session','From → to','Overlap']:tab==='sessions'?['Session','Reason']:['Start · ET','End · ET','Minutes','Classification']).map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>
            {tab==='rolls'&&continuous.rolls.slice(from,from+pageSize).map(r=><tr key={r.roll_id}><td>{dateLabel(r.trading_date)}</td><td>{r.old_contract} → {r.new_contract}</td><td><span className={r.overlap?.status==='unresolved'?'quality-badge warning':'quality-badge'}>{r.overlap?.status==='unresolved'?'Needs review':r.overlap?'Observed overlap':'Calendar transition'}</span></td></tr>)}
            {tab==='sessions'&&continuous.ineligible_sessions.slice(from,from+pageSize).map(s=><tr key={s.trading_date}><td>{dateLabel(s.trading_date)}</td><td title={s.quality_flags}>{s.quality_flags.split(';').map(reason=>reasons[reason]||reason.replaceAll('_',' ').toLowerCase()).join(' · ')}</td></tr>)}
            {tab==='gaps'&&gaps.map((g,i)=><tr key={i}><td>{timeLabel(g.start_utc)}</td><td>{timeLabel(g.end_exclusive_utc)}</td><td>{g.minutes}</td><td>{g.classification}</td></tr>)}
            {!total&&<tr><td colSpan={4}>No records for this view.</td></tr>}
          </tbody></table>}
        </div>
        <footer className="quality-footer"><span>{total?`${count(from+1)}–${count(Math.min(from+pageSize,total))} of ${count(total)}`:'No records'}</span><div><button aria-label="Previous quality page" disabled={!page||loading} onClick={()=>setPage(p=>p-1)}>Previous</button><button aria-label="Next quality page" disabled={from+pageSize>=total||loading} onClick={()=>setPage(p=>p+1)}>Next</button></div></footer>
        <a className="quality-download" href="/api/continuous/manifest" target="_blank" rel="noreferrer">Open full provenance report ↗</a>
      </section>
    </dialog>,document.body)}
  </div>;
}
