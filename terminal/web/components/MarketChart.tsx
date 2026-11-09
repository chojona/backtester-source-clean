"use client";
import { useEffect, useRef, useState } from "react";
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
  type UTCTimestamp,
} from "lightweight-charts";
import { Bar, Snapshot, fmt, clock } from "@/lib/types";
import Drawings from "./Drawings";
import ResearchOverlay from "./ResearchOverlay";
import ContinuousOverlay from "./ContinuousOverlay";
import {indicatorPoints} from "@/lib/continuous";
import { Indicators, readLocal, writeLocal } from "@/lib/workspace";
export default function MarketChart({
  data,
  vwap,
  levels,
  opening,
  settings,
  replay,
  datasetHash,
}: {
  data: Snapshot | null;
  vwap: boolean;
  levels: boolean;
  opening: boolean;
  settings: Indicators;
  replay: boolean;
  datasetHash?: string;
}) {
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
  const lastReplay = useRef<{
    id: string;
    cursor: number;
    count: number;
  } | null>(null);
  const [hover, setHover] = useState<Bar | null>(null);
  const [rollsVisible,setRollsVisible]=useState(false);
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
          if(!dataRef.current?.continuous || dataRef.current.continuous.history_sessions===1)return clock(time);
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
    c.timeScale().subscribeVisibleTimeRangeChange((range) => {
      if (identity.current && range && !updating.current)
        writeLocal("nq:v2:view:" + identity.current, range);
    });
    c.subscribeCrosshairMove((p) => {
      const b = dataRef.current?.bars.find((b) => b.time === p.time);
      setHover(b ?? null);
    });
    return () => {
      c.remove();
      chart.current = null;
      series.current = null;
    };
  }, []);
  useEffect(() => {
    const s = series.current,
      c = chart.current;
    if (!s || !c) return;
    const bars = data?.bars ?? [];
    c.timeScale().applyOptions({minBarSpacing:data?.continuous ? 0.02 : 0.5});
    const id = data
      ? `${data.contract}/${data.session}/${data.timeframe}/${data.display || "Globex"}${replay ? "/replay" : ""}${data.continuous ? `/history/${data.continuous.history_sessions}` : ""}`
      : "";
    const nextRange =
      identity.current !== id
        ? readLocal<{ from: UTCTimestamp; to: UTCTimestamp } | null>(
            "nq:v2:view:" + id,
            null,
          )
        : null;
    const beforeRange = c.timeScale().getVisibleLogicalRange();
    const prior = lastReplay.current;
    updating.current = true;
    const candles=bars.map(b=>({...b,time:b.time as UTCTimestamp,color:b.eligible_full_session===false?'#637084':undefined,wickColor:b.eligible_full_session===false?'#637084':undefined}));
    const times=new Set(bars.map(b=>b.time));
    const missing=data?.timeframe==='1m' ? (data?.continuous?.gaps||[]).map(g=>Math.floor(Date.parse(g.start_utc)/1000)).filter(t=>!times.has(t)) : [];
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
        indicatorPoints(bars,field,!!data?.continuous).map(point=>({...point,time:point.time as UTCTimestamp})),
      );
      const opt =
        settings[
          key === "vwap"
            ? "vwap"
            : key === "upper" || key === "lower"
              ? "bands"
              : "opening"
        ];
      s[key].applyOptions({
        visible:
          key === "vwap"
            ? vwap
            : key === "upper" || key === "lower"
              ? opt.visible
              : opening,
        color: opt.color,
        lineStyle: opt.style,
      });
    }
    if (identity.current !== id) {
      if (nextRange && bars.length && !replay) {
        try {
          c.timeScale().setVisibleRange(nextRange);
        } catch {
          c.timeScale().fitContent();
        }
      } else if (replay) {
        const to = Math.max(96, bars.length + 5);
        c.timeScale().setVisibleLogicalRange({ from: to - 96, to });
      } else c.timeScale().fitContent();
      identity.current = id;
      setHover(null);
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
    } else lastReplay.current = null;
    updating.current = false;
    const savedRange = c.timeScale().getVisibleRange();
    if (id && savedRange) writeLocal("nq:v2:view:" + id, savedRange);
  }, [data, vwap, opening, settings, replay]);
  useEffect(() => {
    const s = series.current;
    if (!s) return;
    const lines: ReturnType<typeof s.candles.createPriceLine>[] = [];
    if (data && levels)
      for (const [title, price] of [
        ["PDH", data.previous.high],
        ["PDL", data.previous.low],
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
  }, [data?.previous.high, data?.previous.low, levels, settings.levels]);
  const active =
    (hover ? data?.bars.find((b) => b.time === hover.time) : null) ??
    data?.bars.at(-1);
  return (
    <div className="chart-wrap clean-chart">
      <div className="chart-header">
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
        <div><button onClick={()=>{const c=chart.current;if(c){c.priceScale('right').applyOptions({autoScale:true});c.timeScale().fitContent();}}}>Fit history</button>
        {data?.continuous && <label className="roll-toggle"><input aria-label="Show rollovers" type="checkbox" checked={rollsVisible} onChange={e=>setRollsVisible(e.target.checked)}/> Rollovers</label>}</div>
      </div>
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
