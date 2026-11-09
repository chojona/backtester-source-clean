"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  ColorType,
  LineStyle,
  TickMarkType,
  type IChartApi,
  type ISeriesApi,
  type LogicalRange,
  type UTCTimestamp,
} from "lightweight-charts";
import { Bar, Snapshot, fmt, clock } from "@/lib/types";
import Drawings from "./Drawings";
import ResearchOverlay from "./ResearchOverlay";
import ContinuousOverlay from "./ContinuousOverlay";
import {indicatorPoints} from "@/lib/continuous";
import { useChartHistory } from "@/lib/useChartHistory";
import type { SeriesIdentity } from "@/lib/chartWindow";
import ContinuousQuality from "./ContinuousQuality";
import { Indicators, readLocal, writeLocal } from "@/lib/workspace";

function atOrBefore(bars: Bar[], time: number) {
  let first = 0, last = bars.length;
  while (first < last) {
    const middle = Math.floor((first + last) / 2);
    if (bars[middle].time <= time) first = middle + 1;
    else last = middle;
  }
  return bars[first - 1];
}

type Viewport = { from: UTCTimestamp; to: UTCTimestamp; day?: string };

export default function MarketChart({
  data: baseData,
  vwap,
  levels,
  opening,
  settings,
  replay,
  datasetHash,
  allowHistory,
  chartSeries,
  historySessions,
}: {
  data: Snapshot | null;
  vwap: boolean;
  levels: boolean;
  opening: boolean;
  settings: Indicators;
  replay: boolean;
  datasetHash?: string;
  allowHistory: boolean;
  chartSeries?: SeriesIdentity;
  historySessions: number;
}) {
  const viewGroup = useRef("");
  const viewportDay = useRef("");
  const start = useRef({ group: "", frame: "", day: "" });
  const group = baseData ? JSON.stringify([chartSeries ?? datasetHash ?? null, baseData.contract,
    baseData.session, baseData.display, replay, historySessions]) : "";
  if (baseData && (start.current.group !== group || start.current.frame !== baseData.timeframe)) {
    const sameSelection = group === viewGroup.current && start.current.frame !== baseData.timeframe;
    const saved = readLocal<Viewport | null>("nq:v3:view:" + group + "/" + baseData.timeframe, null);
    const savedDay = saved?.day && /^\d{4}-\d{2}-\d{2}$/.test(saved.day) ? saved.day : "";
    start.current = { group, frame: baseData.timeframe, day:
      !replay && historySessions !== 5000
        ? (sameSelection ? viewportDay.current : savedDay) || baseData.session
        : baseData.session };
  }
  const history = useChartHistory(allowHistory && !replay ? baseData : null, chartSeries, historySessions, start.current.day);
  const data = history.data ?? baseData;
  const historyRef = useRef(history);
  historyRef.current = history;
  const host = useRef<HTMLDivElement>(null),
    chart = useRef<IChartApi | null>(null);
  const series = useRef<{
    candles: ISeriesApi<"Candlestick">;
    volume: ISeriesApi<"Histogram">;
    vwap: ISeriesApi<"Line">;
    oh: ISeriesApi<"Line">;
    ol: ISeriesApi<"Line">;
    upper: ISeriesApi<"Line">;
    lower: ISeriesApi<"Line">;
  } | null>(null);
  const [apis, setApis] = useState<{
    chart: IChartApi;
    series: ISeriesApi<"Candlestick">;
  } | null>(null);
  const updating = useRef(false);
  const dataRef = useRef(data);
  dataRef.current = data;
  const drawingTools=useRef<HTMLDivElement>(null);
  const identity = useRef("");
  const savedViewport = useRef<Viewport | null>(null);
  const restoreViewport = useRef<typeof savedViewport.current>(null);
  const lastBars = useRef<Bar[] | null>(null);
  const fullHistoryFit = useRef("");
  const restoreFullHistoryView = useRef(false);
  const [rollsVisible, setRollsVisible] = useState(false);
  useEffect(() => setRollsVisible(readLocal<boolean>("nq:v3:show-rolls", false) === true), []);
  const lastReplay = useRef<{
    id: string;
    cursor: number;
    count: number;
  } | null>(null);
  const [hover, setHover] = useState<Bar | null>(null);
  useEffect(() => {
    if (!host.current) return;
    const c = createChart(host.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#0c1119" },
        textColor: "#7c899d",
        fontFamily: "ui-monospace, SFMono-Regular, monospace",
        fontSize: 11,
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: "#161e2a" },
        horzLines: { color: "#161e2a" },
      },
      rightPriceScale: {
        borderColor: "#202b3a",
        scaleMargins: { top: 0.09, bottom: 0.24 },
      },
      timeScale: {
        borderColor: "#202b3a",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        lockVisibleTimeRangeOnResize: true,
        tickMarkFormatter: (time: number, kind: TickMarkType) => {
          if(dataRef.current?.bars[0]?.trading_date === dataRef.current?.bars.at(-1)?.trading_date && dataRef.current?.timeframe !== "daily")return clock(time);
          const date=new Date(time*1000);
          if(kind===TickMarkType.Year)return date.toLocaleDateString("en-US",{timeZone:"America/New_York",year:"numeric"});
          if(kind===TickMarkType.Month)return date.toLocaleDateString("en-US",{timeZone:"America/New_York",month:"short",year:"2-digit"});
          if(kind===TickMarkType.DayOfMonth)return date.toLocaleDateString("en-US",{timeZone:"America/New_York",month:"short",day:"numeric"});
          return clock(time);
        },
      },
      localization: {
        timeFormatter: (time: number) =>
          `${new Date(time * 1000).toLocaleDateString("en-US", { timeZone: "America/New_York" })} ${clock(time)} ET`,
      },
      crosshair: {
        vertLine: { color: "#677489", labelBackgroundColor: "#2a384c" },
        horzLine: { color: "#677489", labelBackgroundColor: "#2a384c" },
      },
    });
    const candles = c.addSeries(CandlestickSeries, {
      upColor: "#32bca4",
      downColor: "#ef6c7c",
      wickUpColor: "#32bca4",
      wickDownColor: "#ef6c7c",
      borderVisible: false,
    });
    const volume = c.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    volume
      .priceScale()
      .applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const line = (color: string) =>
      c.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    series.current = {
      candles,
      volume,
      vwap: line("#deb568"),
      oh: line("#779bea"),
      ol: line("#779bea"),
      upper: line("#65a89a"),
      lower: line("#65a89a"),
    };
    chart.current = c;
    setApis({ chart: c, series: candles });
    const plot = host.current;
    const scale = c.timeScale();
    let gesture: { pointer: number; range: LogicalRange; scope: string } | null = null;
    let wheel: { range: LogicalRange; scope: string } | null = null;
    let frame = 0;
    const checkPan = (before: LogicalRange, scope: string) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const loader = historyRef.current;
        const after = scale.getVisibleLogicalRange();
        if (!loader.enabled || loader.pending || loader.failed || !after ||
            identity.current !== scope || updating.current) return;
        const bars = candles.barsInLogicalRange(after);
        if (!bars) return;
        const threshold = Math.min(64, (after.to - after.from) * 0.2);
        if (after.from < before.from - 0.5 && after.to < before.to - 0.5 && bars.barsBefore < threshold)
          void loader.load("older");
        else if (after.from > before.from + 0.5 && after.to > before.to + 0.5 && bars.barsAfter < threshold)
          void loader.load("newer");
      });
    };
    const onRange = () => {
      if (updating.current) return;
      const range = scale.getVisibleRange();
      if (identity.current && range && dataRef.current) {
        viewportDay.current = atOrBefore(dataRef.current.bars, Number(range.to))?.trading_date ?? "";
        savedViewport.current = { from: range.from as UTCTimestamp, to: range.to as UTCTimestamp,
          day: viewportDay.current };
        writeLocal("nq:v3:view:" + identity.current, savedViewport.current);
      }
      const intent = gesture ?? wheel;
      if (intent) checkPan(intent.range, intent.scope);
    };
    scale.subscribeVisibleLogicalRangeChange(onRange);
    c.subscribeCrosshairMove((p) => {
      if (!p.time) return setHover(null);
      const bar = atOrBefore(dataRef.current?.bars ?? [], Number(p.time));
      setHover(bar?.time === p.time ? bar : null);
    });
    const startPan = (event: PointerEvent) => {
      const range = scale.getVisibleLogicalRange();
      if (event.isPrimary && event.button === 0 && range && historyRef.current.enabled)
        gesture = { pointer: event.pointerId, range, scope: identity.current };
    };
    const endPan = (event: PointerEvent) => {
      if (gesture?.pointer !== event.pointerId) return;
      if (event.type === "pointerup") checkPan(gesture.range, gesture.scope);
      gesture = null;
    };
    const scrollPan = (event: WheelEvent) => {
      const range = scale.getVisibleLogicalRange();
      if (range && historyRef.current.enabled && Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
        wheel = { range, scope: identity.current };
        checkPan(range, identity.current);
        requestAnimationFrame(() => { wheel = null; });
      }
    };
    plot.addEventListener("pointerdown", startPan);
    window.addEventListener("pointerup", endPan);
    window.addEventListener("pointercancel", endPan);
    plot.addEventListener("wheel", scrollPan, { capture: true, passive: true });
    return () => {
      cancelAnimationFrame(frame);
      scale.unsubscribeVisibleLogicalRangeChange(onRange);
      plot.removeEventListener("pointerdown", startPan);
      window.removeEventListener("pointerup", endPan);
      window.removeEventListener("pointercancel", endPan);
      plot.removeEventListener("wheel", scrollPan, true);
      c.remove();
      chart.current = null;
      series.current = null;
    };
  }, []);
  useLayoutEffect(() => {
    const s = series.current,
      c = chart.current;
    if (!s || !c) return;
    if (lastBars.current === (data?.bars ?? null)) return;
    lastBars.current = data?.bars ?? null;
    const bars = data?.bars ?? [];
    const scale = c.timeScale();
    const legacyId = data
      ? [data.contract, data.session, data.timeframe, data.display, ...(replay ? ["replay"] :
          data.continuous ? ["history", String(historySessions)] : [])].join("/")
      : "";
    const id = data ? group + "/" + data.timeframe : "";
    const changed = Boolean(id && id !== identity.current);
    const beforeRange = scale.getVisibleLogicalRange();
    const visible = scale.getVisibleRange();
    if (changed) {
      const persisted = readLocal<typeof savedViewport.current>("nq:v3:view:" + id, null) ??
        (data?.contract === "NQ1! Adjusted" ? null : readLocal<typeof savedViewport.current>("nq:v2:view:" + legacyId, null));
      restoreViewport.current = replay ? null :
        (group === viewGroup.current ? savedViewport.current : null) ?? persisted;
      restoreFullHistoryView.current = Boolean(persisted && Number.isFinite(persisted.from) && Number.isFinite(persisted.to));
    }
    const anchors = !replay && !changed && visible
      ? [visible.from, visible.to].map(time => ({ time, index: scale.timeToIndex(time) }))
      : [];
    const started = performance.now();
    const prior = lastReplay.current;
    updating.current = true;
    if (!data) setHover(null);
    const candles=bars.map(b=>({open:b.open,high:b.high,low:b.low,close:b.close,time:b.time as UTCTimestamp,color:b.eligible_full_session===false?'#637084':undefined,wickColor:b.eligible_full_session===false?'#637084':undefined}));
    const times=new Set(bars.map(b=>b.time));
    const missing=data?.timeframe==='1m' ? [...new Set((data?.continuous?.gaps||[]).map(g=>Math.floor(Date.parse(g.start_utc)/1000)))].filter(t=>!times.has(t)) : [];
    s.candles.setData([...candles,...missing.map(time=>({time:time as UTCTimestamp}))].sort((a,b)=>Number(a.time)-Number(b.time)));
    s.volume.setData(
      bars.map((b) => ({
        time: b.time as UTCTimestamp,
        value: b.volume,
        color: b.close >= b.open ? "#32bca435" : "#ef6c7c35",
      })),
    );
    for (const [key, field] of [
      ["vwap", "vwap"],
      ["oh", "or_high"],
      ["ol", "or_low"],
      ["upper", "vwap_upper"],
      ["lower", "vwap_lower"],
    ] as const) {
      s[key].setData(
        indicatorPoints(bars,field,Boolean(bars[0]?.trading_date)).map(point=>({...point,time:point.time as UTCTimestamp})),
      );
    }
    if (host.current) {
      host.current.dataset.candles = String(bars.length);
      host.current.dataset.setDataMs = (performance.now() - started).toFixed(2);
      host.current.dataset.setDataCount = String(Number(host.current.dataset.setDataCount ?? 0) + 1);
    }
    scale.applyOptions({ minBarSpacing: data?.continuous ? 0.02 : 0.5 });
    if (changed) {
      identity.current = id;
      viewGroup.current = group;
      setHover(null);
      if (replay) {
        const to = Math.max(96, bars.length + 5);
        scale.setVisibleLogicalRange({ from: to - 96, to });
      } else scale.fitContent();
    } else if (beforeRange) {
      for (const anchor of anchors) {
        const index = scale.timeToIndex(anchor.time);
        if (index === null || anchor.index === null) continue;
        const shift = index - anchor.index;
        scale.setVisibleLogicalRange({ from: beforeRange.from + shift, to: beforeRange.to + shift });
        break;
      }
    }
    const target = restoreViewport.current;
    if (data && !replay && target && Number.isFinite(target.from) && Number.isFinite(target.to) &&
        target.from <= target.to && bars.length && target.from <= bars.at(-1)!.available_at &&
        target.to >= bars[0].time &&
        (target.from >= bars[0].time || Boolean(history.window && !history.pending))) {
      // Convert UTC endpoints to this frame's actual observations, including a daily bucket.
      const from = scale.timeToIndex(target.from, true);
      const to = scale.timeToIndex(target.to, true);
      if (from !== null && to !== null) scale.setVisibleLogicalRange({ from, to: Math.max(from + 2, to) });
      restoreViewport.current = null;
    }
    if (replay && data && bars.length) {
      const span = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        daily: 1440,
      }[data.timeframe];
      const jumped =
        prior && prior.id === id && Math.abs(data.cursor - prior.cursor) > span;
      const following =
        prior && beforeRange && beforeRange.to >= prior.count - 3;
      if (
        prior?.id === id &&
        (jumped || following) &&
        data.cursor !== prior.cursor
      ) {
        const width = jumped
            ? 96
            : Math.max(
                12,
                beforeRange ? beforeRange.to - beforeRange.from : 96,
              ),
          to = Math.max(width, bars.length + 5);
        c.timeScale().setVisibleLogicalRange({ from: to - width, to });
      }
      lastReplay.current = { id, cursor: data.cursor, count: bars.length };
    } else if (!replay) lastReplay.current = null;
    updating.current = false;
    const savedRange = c.timeScale().getVisibleRange();
    if (id && savedRange) {
      viewportDay.current = atOrBefore(bars, Number(savedRange.to))?.trading_date ?? "";
      savedViewport.current = { from: savedRange.from as UTCTimestamp, to: savedRange.to as UTCTimestamp,
        day: viewportDay.current };
      if (!restoreViewport.current) writeLocal("nq:v3:view:" + id, savedViewport.current);
    }
  }, [data, replay, group, historySessions, history.window, history.pending]);
  useEffect(() => {
    const s = series.current;
    if (!s) return;
    for (const [key, opt, visible] of [
      ["vwap", settings.vwap, vwap], ["oh", settings.opening, opening], ["ol", settings.opening, opening],
      ["upper", settings.bands, settings.bands.visible], ["lower", settings.bands, settings.bands.visible],
    ] as const) s[key].applyOptions({ visible, color: opt.color, lineStyle: opt.style });
  }, [vwap, opening, settings]);
  useEffect(() => {
    if (historySessions !== 5000 || data?.timeframe !== "daily" || !history.scope ||
        !history.edges?.older || history.pending || fullHistoryFit.current === history.scope) return;
    fullHistoryFit.current = history.scope;
    if (!restoreFullHistoryView.current) chart.current?.timeScale().fitContent();
  }, [data?.timeframe, history.scope, history.edges?.older, history.pending, historySessions]);
  const hovered = hover && data ? atOrBefore(data.bars, hover.time) : undefined;
  const active = hovered?.time === hover?.time && hovered ? hovered : data?.bars.at(-1);
  const activeDay = active?.trading_date;
  const previous = activeDay ? history.window?.session_context[activeDay]?.previous ??
    (activeDay === data?.session ? data.previous : undefined) : data?.previous;
  useLayoutEffect(() => {
    const s = series.current;
    if (!s) return;
    const lines: ReturnType<typeof s.candles.createPriceLine>[] = [];
    if (previous && levels)
      for (const [title, price] of [
        ["PDH", previous.high],
        ["PDL", previous.low],
      ] as const) {
        if (price !== null)
          lines.push(
            s.candles.createPriceLine({
              price,
              title,
              color: settings.levels.color,
              lineWidth: 1,
              lineStyle: settings.levels.style,
              axisLabelVisible: true,
            }),
          );
      }
    return () => lines.forEach((l) => s.candles.removePriceLine(l));
  }, [previous?.high, previous?.low, levels, settings.levels]);
  return (
    <div className="chart-wrap clean-chart">
      <div className="chart-header">
      {data?.continuous && <ContinuousQuality data={data} />}
      <div className="chart-readout">
        <span className="chart-symbol">
          {data?.contract || "NQ"}{" "}
          <span>· {data?.timeframe || "1m"} · CME</span>
        </span>
        <div className="ohlc">
          {(["open", "high", "low", "close"] as const).map((k, i) => (
            <span key={k}>
              {["O", "H", "L", "C"][i]}{" "}
              <b className={k === "close" ? "teal" : ""}>{fmt(active?.[k])}</b>
            </span>
          ))}
          <span>
            Vol <b>{fmt(active?.volume, 0)}</b>
          </span>
        </div>
      </div>
      {data?.continuous && <div className="continuous-readout" data-testid="continuous-readout" title={`Raw OHLC ${active?.raw_open}, ${active?.raw_high}, ${active?.raw_low}, ${active?.raw_close}; offset ${active?.adjustment_offset}; Roll ${active?.roll_id || 'initial'}; adjustment ${active?.adjustment_status || 'unadjusted'}`}>
        Source {active?.source_contract || data.continuous.source_contract} · raw close {fmt(active?.raw_close)} · offset {fmt(active?.adjustment_offset)} · {active?.retrospective ? `retrospective block ${active?.adjustment_block_id}` : 'unadjusted'} · {active?.eligible_full_session ? 'research eligible (not certified)' : 'research ineligible'}

      </div>}
      <div className="chart-legend">
        {vwap && (
          <span>
            <i className="dot gold" />
            Session VWAP <b>{fmt(active?.vwap)}</b>
          </span>
        )}
        {opening && (
          <span>
            <i className="dot blue" />
            Opening range · {settings.openingMinutes}m
          </span>
        )}
        {levels && (
          <span>
            <i className="dot gray" />
            Previous session H/L
          </span>
        )}
      </div>
      <div className="chart-view-controls">
        {data?.continuous && <span className="coverage-label" data-testid="continuous-coverage">{data.bars.length ? `${data.bars[0].trading_date} → ${data.bars.at(-1)?.trading_date}` : 'No observations'} · {data.continuous.history_sessions.toLocaleString()} sessions</span>}
        {!data?.continuous && history.window && <span className="coverage-label" data-testid="chart-history-coverage">
          {history.window.session_dates[0]} → {history.window.session_dates.at(-1)} · {history.window.session_dates.length} sessions
        </span>}
        <div><button onClick={()=>{const c=chart.current;if(c){c.priceScale('right').applyOptions({autoScale:true});c.timeScale().fitContent();}}}>Fit history</button>
        {data?.continuous && <label className="roll-toggle"><input aria-label="Show rollovers" type="checkbox" checked={rollsVisible} onChange={e=>{setRollsVisible(e.target.checked);writeLocal("nq:v3:show-rolls",e.target.checked);}}/> Rollovers</label>}</div>
      </div>
      {history.enabled && <div className="chart-view-controls" role="status" data-testid="intraday-history">
        {history.pending ? (history.pending === "initial" ? "Loading chart history…" : `Loading ${history.pending} sessions…`) :
          history.failed ? <span>Could not load {history.failed} sessions. <button onClick={() => void history.load(history.failed!)}>Retry history</button>
            {history.failed !== "initial" && <button onClick={() => void history.load("initial")}>Reload history</button>}</span> :
          history.edges?.older && history.edges?.newer ? "All available history edges reached." :
          history.edges?.older ? "Earliest session reached. Pan right for later sessions." :
          history.edges?.newer ? "Latest session reached. Pan left for earlier sessions." :
          "Pan at either edge to load more historical sessions."}
        {history.edges && data?.bars.length === 0 && !history.pending && !history.failed && <div>
          {!history.edges.older && <button onClick={() => void history.load("older")}>Older sessions</button>}
          {!history.edges.newer && <button onClick={() => void history.load("newer")}>Newer sessions</button>}
        </div>}
      </div>}
      <div className="chart-drawing-tools" ref={drawingTools} />
      </div>
      <div className="chart-plot">
      <div
        ref={host}
        className="chart-canvas"
        aria-label="Historical NQ candlestick chart"
        data-testid="market-chart"
      />
      {apis && (<>
        <ResearchOverlay chart={apis.chart} series={apis.series} data={data} replay={replay} datasetHash={datasetHash} />
        {rollsVisible && <ContinuousOverlay chart={apis.chart} series={apis.series} data={data} host={host.current} />}
        <Drawings
          chartSeries={chartSeries}
          replay={replay}
          chart={apis.chart}
          series={apis.series}
          data={data}
          settings={settings}
          toolbarTarget={drawingTools.current}
        />
      </>)}
      <div className="chart-watermark">
        NQ<span>NASDAQ 100 FUTURES</span>
      </div>
      </div>
    </div>
  );
}
