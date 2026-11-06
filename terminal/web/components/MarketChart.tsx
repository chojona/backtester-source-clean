"use client";
import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  ColorType,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { Bar, Snapshot, fmt, clock } from "@/lib/types";
export default function MarketChart({
  data,
  vwap,
  levels,
  opening,
}: {
  data: Snapshot | null;
  vwap: boolean;
  levels: boolean;
  opening: boolean;
}) {
  const host = useRef<HTMLDivElement>(null),
    chart = useRef<IChartApi | null>(null);
  const series = useRef<{
    candles: ISeriesApi<"Candlestick">;
    volume: ISeriesApi<"Histogram">;
    vwap: ISeriesApi<"Line">;
    oh: ISeriesApi<"Line">;
    ol: ISeriesApi<"Line">;
  } | null>(null);
  const dataRef = useRef(data);
  dataRef.current = data;
  const identity = useRef("");
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
        tickMarkFormatter: (time: number) => clock(time),
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
    };
    chart.current = c;
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
    s.candles.setData(
      bars.map((b) => ({ ...b, time: b.time as UTCTimestamp })),
    );
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
    ] as const) {
      s[key].setData(
        bars
          .filter((b) => b[field] !== null)
          .map((b) => ({ time: b.time as UTCTimestamp, value: b[field]! })),
      );
      s[key].applyOptions({ visible: key === "vwap" ? vwap : opening });
    }
    const id = data ? `${data.contract}/${data.session}/${data.timeframe}` : "";
    if (identity.current !== id) {
      c.timeScale().fitContent();
      identity.current = id;
      setHover(null);
    }
  }, [data, vwap, opening]);
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
              color: "#657793",
              lineWidth: 1,
              lineStyle: LineStyle.Dashed,
              axisLabelVisible: true,
            }),
          );
      }
    return () => lines.forEach((l) => s.candles.removePriceLine(l));
  }, [data?.previous.high, data?.previous.low, levels]);
  const active =
    (hover ? data?.bars.find((b) => b.time === hover.time) : null) ??
    data?.bars.at(-1);
  return (
    <div className="chart-wrap">
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
      <div
        ref={host}
        className="chart-canvas"
        aria-label="Historical NQ candlestick chart"
        data-testid="market-chart"
      />
      <div className="chart-watermark">
        NQ<span>NASDAQ 100 FUTURES</span>
      </div>
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
            Opening range · 30m
          </span>
        )}
        {levels && (
          <span>
            <i className="dot gray" />
            Previous session H/L
          </span>
        )}
      </div>
    </div>
  );
}
