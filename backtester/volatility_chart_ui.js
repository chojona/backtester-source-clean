/* Local TradingView Lightweight Charts integration. No network/data API calls. */
(()=>{
'use strict';
const data=JSON.parse(document.getElementById('chart-data').textContent);
const L=window.LightweightCharts,D=window.VolatilityChartData;
const $=id=>document.getElementById(id);
const color={blue:'#7eb6e0',teal:'#1f9d78',rose:'#d35d55',gold:'#d7a15a',purple:'#8d7fd4',wickUp:'#b7e0d2',wickDown:'#f0c2bc'};
const shortTime=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hour12:false});
const fullTime=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});
const dayTime=new Intl.DateTimeFormat('en-US',{timeZone:'UTC',month:'short',day:'numeric'});
const formatPrice=new Intl.NumberFormat('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const formatVolume=new Intl.NumberFormat('en-US');
const compact=v=>Math.abs(v)>=1000?(v/1000).toFixed(1)+'k':v.toFixed(Math.abs(v)<.01?4:Math.abs(v)<1?3:1);
const dateValue=t=>typeof t==='number'?t*1000:typeof t==='string'?Date.parse(t+'T00:00:00Z'):Date.UTC(t.year,t.month-1,t.day);
let chosen=-1,interval=5,style='candles',current=null,loading=false;
const intraday=[],overview=[];
function makeChart(id,daily=false){
 const chart=L.createChart($(id),{
  autoSize:true,
  layout:{background:{type:L.ColorType.Solid,color:'#101722'},textColor:'#c4bfb4',fontFamily:'Avenir Next, Segoe UI, sans-serif',fontSize:12,
    attributionLogo:true,panes:{separatorColor:'#2a3344',separatorHoverColor:'#8d6a3a',enableResize:true}},
  grid:{vertLines:{color:'#1c2430'},horzLines:{color:'#1c2430'}},
  leftPriceScale:{visible:false},
  rightPriceScale:{visible:true,borderColor:'#2c3544',minimumWidth:76,autoScale:true,scaleMargins:{top:.14,bottom:.1},entireTextOnly:false},
  timeScale:{borderColor:'#283549',timeVisible:!daily,secondsVisible:false,barSpacing:7,minBarSpacing:.05,rightOffset:5,
    tickMarkFormatter:t=>daily?dayTime.format(dateValue(t)):shortTime.format(dateValue(t)),
    shiftVisibleRangeOnNewBar:false},
  crosshair:{mode:L.CrosshairMode.Normal,vertLine:{color:'#7188a6',style:L.LineStyle.Dashed,labelBackgroundColor:'#2e4664'},
    horzLine:{color:'#7188a6',style:L.LineStyle.Dashed,labelBackgroundColor:'#2e4664'}},
  localization:{timeFormatter:t=>daily?dayTime.format(dateValue(t)):fullTime.format(dateValue(t))},
  handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},
  handleScale:{axisPressedMouseMove:{time:true,price:true},axisDoubleClickReset:{time:true,price:true},mouseWheel:true,pinch:true},
 });
 const item={chart,id,series:[],daily};
 const host=$(id);
 host.title='Drag to pan · Scroll to zoom · Drag the right axis to scale · Double-click an axis to reset · +/− to zoom · Home restores a readable window';
 host.tabIndex=0;
 (daily?overview:intraday).push(item);
 const controls=document.createElement('div');
 controls.className='controls view-controls';
 controls.setAttribute('aria-label','Chart view controls');
 for(const [label,description,action] of [
   ['−','Zoom out',()=>zoom(item,1.4)],
   ['+','Zoom in',()=>zoom(item,1/1.4)],
   ['Reset','Readable window and vertical scale',()=>resetView(item)],
 ]){
   const button=document.createElement('button');button.type='button';button.textContent=label;
   button.title=description;button.setAttribute('aria-label',description);
   button.addEventListener('click',action);controls.append(button);
 }
 host.closest('.chart').querySelector('.chart-header').append(controls);
 host.addEventListener('keydown',event=>{
   if(event.key==='+'||event.key==='='){zoom(item,1/1.4);event.preventDefault();}
   else if(event.key==='-'){zoom(item,1.4);event.preventDefault();}
   else if(event.key==='Home'){resetView(item);event.preventDefault();}
   else if(event.key==='ArrowLeft'||event.key==='ArrowRight'){
     const ts=chart.timeScale(),r=ts.getVisibleLogicalRange();if(!r)return;
     const shift=(r.to-r.from)*.1*(event.key==='ArrowLeft'?-1:1);
     ts.setVisibleLogicalRange({from:r.from+shift,to:r.to+shift});event.preventDefault();
   }
 });
 chart.subscribeCrosshairMove(param=>{
   if(loading)return;
   if(param.point&&Number.isFinite(param.logical))item.cursorLogical=param.logical;
   if(id==='trading')updateHud(param);
 });
 return item;
}
function addLine(item,points,lineColor,extra={}){
 const api=item.chart.addSeries(L.LineSeries,{priceScaleId:'right',color:lineColor,lineWidth:2,priceLineVisible:false,lastValueVisible:false,
    crosshairMarkerVisible:true,pointMarkersVisible:points.length===1,
    priceFormat:{type:'custom',formatter:compact,minMove:.000001},...extra});
 api.setData(points);item.series.push({api,points});return api;
}
function addColumns(item,points,columnColor){
 const api=item.chart.addSeries(L.HistogramSeries,{priceScaleId:'right',base:0,color:columnColor,priceLineVisible:false,lastValueVisible:false,
    priceFormat:{type:'custom',formatter:compact,minMove:.000001}});
 api.setData(points);item.series.push({api,points});return api;
}
function clearLines(item){for(const entry of item.series)item.chart.removeSeries(entry.api);item.series=[];}
const trading=makeChart('trading');
const priceFormat={type:'price',precision:2,minMove:.01};
const candles=trading.chart.addSeries(L.CandlestickSeries,{priceScaleId:'right',upColor:color.teal,downColor:color.rose,
 wickUpColor:color.wickUp,wickDownColor:color.wickDown,borderVisible:true,borderUpColor:'#18785c',borderDownColor:'#a34740',
 priceLineVisible:false,lastValueVisible:true,priceFormat});
const ohlc=trading.chart.addSeries(L.BarSeries,{priceScaleId:'right',upColor:color.teal,downColor:color.rose,thinBars:false,openVisible:true,
 visible:false,priceLineVisible:false,lastValueVisible:true,priceFormat});
const volume=trading.chart.addSeries(L.HistogramSeries,{priceScaleId:'right',priceFormat:{type:'volume'},priceLineVisible:false,lastValueVisible:false,base:0},1);
const candleMarkers=L.createSeriesMarkers(candles,[]),barMarkers=L.createSeriesMarkers(ohlc,[]);
trading.chart.panes()[0].setStretchFactor(5);
trading.chart.panes()[1].setStretchFactor(1.35);
const returns=makeChart('returns'),cumulative=makeChart('cumulative'),profile=makeChart('profile');
function updateHud(param){
 if(!current)return;
 const target=param&&param.time!==undefined?D.exactAt(current.ohlc,param.time):current.ohlc[current.count-1];
 const el=$('ohlc');el.replaceChildren();
 if(!target)return;
 const vol=D.exactAt(current.volume,target.time);
 for(const [label,value] of [['O',target.open],['H',target.high],['L',target.low],['C',target.close],['V',vol?.value]]){
  if(value===undefined)continue;const span=document.createElement('span');span.append(label+' ');const b=document.createElement('b');
  b.textContent=label==='V'?formatVolume.format(value):formatPrice.format(value);span.append(b);el.append(span);
 }
}
function stylePrice(){
 candles.applyOptions({visible:style==='candles'});ohlc.applyOptions({visible:style==='bars'});
 for(const entry of trading.series)if(entry.api===candles||entry.api===ohlc)entry.hidden=(entry.api===candles?style!=='candles':style!=='bars');
}
function setPriceData(){
 current=D.applyTimeframe(data.sessions[chosen]||null,interval,{candles,ohlc,volume},data.sessions);
 const markers=current.rolls.map(roll=>({time:roll.time,position:'aboveBar',shape:'circle',color:color.gold,text:roll.from+' → '+roll.to}));
 candleMarkers.setMarkers(markers);barMarkers.setMarkers(markers);
 trading.series=[{api:candles,points:current.ohlc},{api:ohlc,points:current.ohlc},{api:volume,points:current.volume}];
 stylePrice();
 const label=({60:'1H',240:'4H',1440:'1D'})[interval]||interval+'m';
 $('bar-count').textContent=label+' · '+current.count.toLocaleString()+' bars'+(chosen<0?' · All sessions · Raw prices · '+current.rolls.length+' contract rolls':interval>=60?' · All complete sessions for '+data.sessions[chosen].contract:'');
 trading.chart.applyOptions({timeScale:{tickMarkFormatter:t=>chosen<0||interval>=60?fullTime.format(dateValue(t)):shortTime.format(dateValue(t))}});
 $('price-empty').hidden=current.count>0;
 updateHud();
}
function resetView(item){
 item.cursorLogical=null;
 if(item.id==='trading')D.applyReadableRange(item.chart,item.series,96,5);
 else if(item.id==='returns')D.applyReadableRange(item.chart,item.series,120,4);
 else if(item.id==='profile')D.applyReadableRange(item.chart,item.series,180,3);
 else D.fitAllData(item.chart,item.series);
}
function zoom(item,factor){
 const ts=item.chart.timeScale(),range=ts.getVisibleLogicalRange();if(!range)return;
 const width=range.to-range.from;if(width<=0)return;
 const anchor=Number.isFinite(item.cursorLogical)?Math.max(range.from,Math.min(range.to,item.cursorLogical)):(range.from+range.to)/2;
 const ratio=Math.max(4,width*factor)/width;
 ts.setVisibleLogicalRange({from:anchor-(anchor-range.from)*ratio,to:anchor+(range.to-anchor)*ratio});
}
function setDefaultView(){resetView(trading);}
function setTimeframe(minutes){
 if(![1,5,15,60,240,1440].includes(minutes))throw new Error('Unsupported interval');
 loading=true;
 try{interval=minutes;setPriceData();document.querySelectorAll('[data-interval]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.interval)===interval)));setDefaultView();}
 finally{loading=false;}
}
function loadSession(index){
 loading=true;
 try{
  chosen=index;const selected=chosen<0?data.sessions:[data.sessions[chosen]];
  const s=selected[0];
  $('price-title').textContent=data.instrument+' / '+(chosen<0?'All sessions':s.contract+(s.complete?'':' · partial'));
  $('references').textContent=chosen<0?'Prior-session profiles':s.references+' prior complete sessions';
  $('observed-legend').hidden=selected.every(session=>session.prefix_complete);
  clearLines(returns);clearLines(cumulative);clearLines(profile);
  let hasProfile=false;
  for(const session of selected){
   for(const run of D.runs(session.series,1))
     addColumns(returns,run.map(point=>({...point,color:point.value>=0?color.teal:color.rose})),color.teal);
   for(const [field,c] of [[2,color.blue],[3,color.gold],[4,color.teal],[5,color.purple],...(!session.prefix_complete?[[7,color.rose]]:[])])
     for(const run of D.runs(session.series,field))addLine(cumulative,run,c,field===7?{lineStyle:L.LineStyle.Dotted}:{});
   const profiles=D.runs(session.series,6);
   for(const run of profiles)addColumns(profile,run,color.purple);
   hasProfile=hasProfile||profiles.length>0;
  }
  $('profile-empty').hidden=hasProfile;
  setPriceData();for(const item of intraday)resetView(item);
 }finally{loading=false;}
}
const allOption=document.createElement('option');allOption.value=-1;allOption.textContent='All sessions';$('session').append(allOption);
for(let i=0;i<data.sessions.length;i++){const option=document.createElement('option');option.value=i;option.textContent=data.sessions[i].date+' · '+data.sessions[i].contract;$('session').append(option);}
$('session').addEventListener('change',()=>loadSession(Number($('session').value)));
document.querySelectorAll('[data-interval]').forEach(button=>button.addEventListener('click',()=>setTimeframe(Number(button.dataset.interval))));
$('chart-style').addEventListener('change',()=>{style=$('chart-style').value;stylePrice();});
$('price-scale').addEventListener('change',()=>{
 const mode=L.PriceScaleMode[$('price-scale').value];
 if(mode===L.PriceScaleMode.Logarithmic&&current&&current.ohlc.some(bar=>bar.low<=0||bar.high<=0)){
  $('price-scale').value='Normal';
  trading.chart.priceScale('right',0).applyOptions({mode:L.PriceScaleMode.Normal,autoScale:true});
  return;
 }
 trading.chart.priceScale('right',0).applyOptions({mode,autoScale:true});
});
$('fullscreen').addEventListener('click',()=>{const panel=$('trading-panel');if(document.fullscreenElement)document.exitFullscreen();else panel.requestFullscreen?.();});
for(const spec of data.overview){
 const item=makeChart('overview-'+spec.id,true);
 for(const field of spec.series){
  const points=field.points.map(p=>p.value===null?{time:p.time}:{time:p.time,value:p.value});
  if(spec.histogram){const api=item.chart.addSeries(L.HistogramSeries,{priceScaleId:'right',base:0,color:field.color,priceFormat:{type:'custom',formatter:compact,minMove:.000001},priceLineVisible:false,lastValueVisible:false});api.setData(points);item.series.push({api,points});}
  else addLine(item,points,field.color,spec.id==='quarticity'?{priceFormat:{type:'custom',formatter:v=>v.toExponential(2),minMove:1e-12}}:{});
 }
 resetView(item);
}
loadSession(-1);
})();
