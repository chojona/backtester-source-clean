"use client";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  TickMarkType,
  type IChartApi,
  type ISeriesApi,
  type LogicalRange,
  type UTCTimestamp,
} from "lightweight-charts";
import { ChevronDown, Maximize } from "lucide-react";
import { Bar, Snapshot, fmt, clock } from "@/lib/types";
import Drawings from "./Drawings";
import ResearchOverlay from "./ResearchOverlay";
import ContinuousOverlay from "./ContinuousOverlay";
import {indicatorPoints} from "@/lib/continuous";
import { useChartHistory } from "@/lib/useChartHistory";
import type { SeriesIdentity } from "@/lib/chartWindow";
import ContinuousQuality from "./ContinuousQuality";
import AuctionTools from "./AuctionTools";
import { defaultIndicators, Indicators, readLocal, writeLocal } from "@/lib/workspace";

function atOrBefore(bars: Bar[], time: number) {
  let first = 0, last = bars.length;
  while (first < last) {
    const middle = Math.floor((first + last) / 2);
    if (bars[middle].time <= time) first = middle + 1;
    else last = middle;
  }
  return bars[first - 1];
}

const candleColors = {
  bullish: { body: "#30b66f", muted: "#65917a" },
  bearish: { body: "#ed626a", muted: "#ab777b" },
  flat: { body: "#ababab", muted: "#888888" },
};

function candleDirection(bar: Bar) {
  if (bar.close > bar.open) return "bullish";
  if (bar.close < bar.open) return "bearish";
  return "flat";
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
  const auctionTools = useRef<HTMLDivElement>(null);
  const drawingRail = useRef<HTMLDivElement>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsId = useId();
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
        background: { type: ColorType.Solid, color: "#303030" },
        textColor: "#d0d0d0",
        fontFamily: "Arial, Helvetica, sans-serif",
        fontSize: 12,
        panes: { separatorColor: "#838383", separatorHoverColor: "#aaa" },
        attributionLogo: true,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false },
      },
      rightPriceScale: {
        borderColor: "#424242",
        scaleMargins: { top: 0.10, bottom: 0.08 },
      },
      timeScale: {
        borderColor: "#424242",
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
        mode: CrosshairMode.Normal,
        vertLine: { color: "#e4e4e4", style: LineStyle.Dashed, labelBackgroundColor: "#202020" },
        horzLine: { color: "#e4e4e4", style: LineStyle.Dashed, labelBackgroundColor: "#202020" },
      },
    });
    const candles = c.addSeries(CandlestickSeries, {
      upColor: candleColors.bullish.body,
      downColor: candleColors.bearish.body,
      wickUpColor: candleColors.bullish.body,
      wickDownColor: candleColors.bearish.body,
      priceFormat: { type: "price", precision: 2, minMove: .25 },
      priceLineStyle: LineStyle.Dotted,
      borderVisible: false,
    });
    const volume = c.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceLineVisible: false,
    }, 1);
    candles.getPane().setStretchFactor(.85);
    volume.getPane().setStretchFactor(.15);
    volume.priceScale().applyOptions({ scaleMargins: { top: .12, bottom: 0 } });
    const line = (color: string, showPrice = false) =>
      c.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: showPrice,
        crosshairMarkerVisible: false,
      });
    series.current = {
      candles,
      volume,
      vwap: line(defaultIndicators.vwap.color, true),
      oh: line(defaultIndicators.opening.color),
      ol: line(defaultIndicators.opening.color),
      upper: line(defaultIndicators.bands.color),
      lower: line(defaultIndicators.bands.color),
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
    const candles = bars.map(b => {
      const direction = candleDirection(b);
      const colors = candleColors[direction];
      const override = b.eligible_full_session === false ? colors.muted : direction === "flat" ? colors.body : undefined;
      return {
        open: b.open, high: b.high, low: b.low, close: b.close, time: b.time as UTCTimestamp,
        color: override, wickColor: override,
      };
    });
    const times=new Set(bars.map(b=>b.time));
    const missing=data?.timeframe==='1m' ? [...new Set((data?.continuous?.gaps||[]).map(g=>Math.floor(Date.parse(g.start_utc)/1000)))].filter(t=>!times.has(t)) : [];
    s.candles.setData([...candles,...missing.map(time=>({time:time as UTCTimestamp}))].sort((a,b)=>Number(a.time)-Number(b.time)));
    s.volume.setData(
      bars.map((b) => ({
        time: b.time as UTCTimestamp,
        value: b.volume,
        color: candleColors[candleDirection(b)].body + "88",
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
      } else {
        const last = bars.at(-1);
        const end = last ? scale.timeToIndex(last.time as UTCTimestamp) : null;
        const visibleBars = Math.max(96, Math.floor(c.paneSize(0).width / 3.5));
        if (data?.timeframe !== "daily" && end !== null && end > visibleBars && !restoreViewport.current) {
          scale.setVisibleLogicalRange({ from: end + 8 - visibleBars, to: end + 8 });
        } else scale.fitContent();
      }
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
  const emptyHistory = Boolean(history.edges && data?.bars.length === 0 && !history.pending && !history.failed);
  const fitHistory = () => {
    const c = chart.current;
    if (!c) return;
    c.priceScale("right").applyOptions({ autoScale: true });
    c.timeScale().fitContent();
  };

  return (
    <div className="chart-wrap clean-chart">
      <div className="chart-header">
        <div className="chart-summary">
          <div className="chart-readout">
            <span className="chart-symbol" title="Nasdaq-100 E-mini Futures · CME">
              <span className="chart-instrument-mark" aria-hidden="true">100</span>
              {data?.contract || "NQ"} <span>· {data?.timeframe || "1m"}</span>
            </span>
            <div className="ohlc">
              {(["open", "high", "low", "close"] as const).map((key, i) => (
                <span key={key}>
                  {["O", "H", "L", "C"][i]} <b>{fmt(active?.[key])}</b>
                </span>
              ))}
              <span>Vol <b>{fmt(active?.volume, 0)}</b></span>
            </div>
          </div>
          <div className="chart-actions">
            <button type="button" className="chart-action" aria-label="Fit history" title="Fit history" onClick={fitHistory}>
              <Maximize size={13} />
            </button>
            <div className="auction-toolbar" ref={auctionTools} />
            <button type="button" className="chart-action" aria-label="Chart details"
              aria-controls={detailsId} aria-expanded={detailsOpen} onClick={() => setDetailsOpen(open => !open)}>
              Details <ChevronDown size={12} />
            </button>
          </div>
        </div>
        <div className="chart-details" id={detailsId} hidden={!detailsOpen}>
          {(vwap || opening || levels) && <section className="chart-detail-group">
            <h3>Indicators</h3>
            <div className="chart-legend">
              {vwap && <span><i className="dot" style={{ backgroundColor: settings.vwap.color }} />
                Session VWAP <b>{fmt(active?.vwap)}</b></span>}
              {opening && <span><i className="dot" style={{ backgroundColor: settings.opening.color }} />
                Opening range · {settings.openingMinutes}m</span>}
              {levels && <span><i className="dot" style={{ backgroundColor: settings.levels.color }} />
                Previous session H/L</span>}
            </div>
          </section>}
          {(data?.continuous || history.window) && <section className="chart-detail-group">
            <h3>History</h3>
            <div className="chart-view-controls">
              {data?.continuous && <span className="coverage-label" data-testid="continuous-coverage">
                {data.bars.length ? `${data.bars[0].trading_date} → ${data.bars.at(-1)?.trading_date}` : "No observations"} · {data.continuous.history_sessions.toLocaleString()} sessions
              </span>}
              {!data?.continuous && history.window && <span className="coverage-label" data-testid="chart-history-coverage">
                {history.window.session_dates[0]} → {history.window.session_dates.at(-1)} · {history.window.session_dates.length} sessions
              </span>}
              {data?.continuous && <label className="roll-toggle">
                <input aria-label="Show rollovers" type="checkbox" checked={rollsVisible} onChange={e => {
                  setRollsVisible(e.target.checked);
                  writeLocal("nq:v3:show-rolls", e.target.checked);
                }} /> Rollovers
              </label>}
            </div>
          </section>}
          {data?.continuous && <section className="chart-detail-group chart-source-strip">
            <h3>Data source</h3>
            <div className="continuous-readout" data-testid="continuous-readout"
              title={`Raw OHLC ${active?.raw_open}, ${active?.raw_high}, ${active?.raw_low}, ${active?.raw_close}; roll ${active?.roll_id || "initial"}`}>
              {active?.source_contract || data.continuous.source_contract} · raw close {fmt(active?.raw_close)} · offset {fmt(active?.adjustment_offset)}
              {" · "}{active?.retrospective ? `retrospective block ${active?.adjustment_block_id}` : "unadjusted"}
              {" · "}{active?.eligible_full_session ? "research eligible (not certified)" : "research ineligible"}
            </div>
            <ContinuousQuality data={data} />
          </section>}
          <section className="chart-detail-group">
            <h3>Drawings</h3>
            <div className="chart-drawing-tools" ref={drawingTools} />
          </section>
        </div>
        {history.enabled && <div className="chart-view-controls chart-history-notice" role="status" data-testid="intraday-history"
          hidden={!detailsOpen && !history.failed && !emptyHistory}>
          {history.pending ? (history.pending === "initial" ? "Loading chart history…" : `Loading ${history.pending} sessions…`) :
            history.failed ? <span>Could not load {history.failed} sessions. <button onClick={() => void history.load(history.failed!)}>Retry history</button>
              {history.failed !== "initial" && <button onClick={() => void history.load("initial")}>Reload history</button>}</span> :
            history.edges?.older && history.edges?.newer ? "All available history edges reached." :
            history.edges?.older ? "Earliest session reached. Pan right for later sessions." :
            history.edges?.newer ? "Latest session reached. Pan left for earlier sessions." :
            "Pan at either edge to load more historical sessions."}
          {emptyHistory && <div>
            {!history.edges?.older && <button onClick={() => void history.load("older")}>Older sessions</button>}
            {!history.edges?.newer && <button onClick={() => void history.load("newer")}>Newer sessions</button>}
          </div>}
        </div>}
      </div>
      <div className="chart-body">
        <div className="chart-drawing-rail" ref={drawingRail} />
        <div className="chart-plot">
          <div
            ref={host}
            className="chart-canvas"
            aria-label="Historical NQ candlestick chart"
            data-testid="market-chart"
          />
          {apis && <>
            <AuctionTools chart={apis.chart} series={apis.series} selected={baseData} data={data}
              identity={chartSeries} replay={replay} target={auctionTools.current} />
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
              railTarget={drawingRail.current}
            />
          </>}
        </div>
      </div>
    </div>
  );
}
