"use client";
import { useLayoutEffect, useMemo, useRef } from "react";
import type { IChartApi, ISeriesApi, ISeriesPrimitive, IPrimitivePaneRenderer, UTCTimestamp } from "lightweight-charts";
import { matchesCoordinate, type AmtSettings, type Context, type Coordinate, type Profile, type Tpo,
  type Value, type Vwap, type VwapPoint } from "@/lib/amt";
import type { Bar, Snapshot } from "@/lib/types";

type Props = {
  chart: IChartApi; series: ISeriesApi<"Candlestick">; data: Snapshot | null;
  profile?: Profile; tpo?: Tpo; vwap?: Vwap; context?: Context;
  settings: AmtSettings; anchor: AmtSettings["anchor"];
};
type PlotPoint = VwapPoint & { candle: number; run: number };

function lowerBound<T>(rows: T[], target: number, time: (item: T) => number) {
  let first = 0, end = rows.length;
  while (first < end) {
    const middle = Math.floor((first + end) / 2);
    if (time(rows[middle]) < target) first = middle + 1;
    else end = middle;
  }
  return first;
}

function plotPoints(bars: Bar[], points: VwapPoint[], coordinate: Coordinate, symbol: string) {
  if (!points.length) return [];
  let index = 0, run = 0;
  const result: PlotPoint[] = [];
  for (let i = lowerBound(bars, points[0].time + 1, b => b.available_at); i < bars.length; i++) {
    const bar = bars[i];
    if (bar.time > points[points.length - 1].time) break;
    while (index < points.length && points[index].time < bar.time) {
      if (points[index].break_before) run++;
      index++;
    }
    const start = index;
    while (index < points.length && points[index].available_at <= bar.available_at) {
      if (points[index].break_before) run++;
      index++;
    }
    if (index > start && matchesCoordinate(bar, coordinate, symbol))
      result.push({ ...points[index - 1], candle: bar.time, run });
    else run++;
  }
  return result;
}

function paint(props: Props, points: PlotPoint[]): IPrimitivePaneRenderer["draw"] {
  return target => target.useMediaCoordinateSpace(({ context: ctx, mediaSize: { width, height } }) => {
    const benchmark = document.documentElement.dataset.amtBenchmark === "1";
    const started = benchmark ? performance.now() : 0;
    const { chart, series, data, profile, tpo, vwap, context, settings, anchor } = props;
    const range = chart.timeScale().getVisibleRange();
    if (!data?.bars.length || !range) return;
    const from = Number(range.from), to = Number(range.to);
    const x = (stamp: number) => chart.timeScale().timeToCoordinate(stamp as UTCTimestamp);
    const y = (price: number) => series.priceToCoordinate(price);
    const tick = (value: number) => y(value * .25);
    const bars = data.bars;
    const oldest = bars[lowerBound(bars, from, b => b.time)];
    const newest = bars[lowerBound(bars, to + 1, b => b.time) - 1];
    const visibleCoordinate = (coordinate: Coordinate | null | undefined) =>
      Boolean(coordinate && oldest && newest && newest.time >= from &&
        matchesCoordinate(oldest, coordinate, data.contract) && matchesCoordinate(newest, coordinate, data.contract));
    const levels = (value: Value | null | undefined, color: string, labels: string[]) => {
      if (!value) return;
      for (const [i, price] of [value.poc.low_tick, value.vah_tick, value.val_tick].entries())
        reference(price, color, labels[i], i === 0);
    };
    const reference = (price: number, color: string, label: string, solid = false) => {
      const py = tick(price);
      if (py === null || py < 0 || py > height) return;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.setLineDash(solid ? [] : [3, 4]);
      ctx.beginPath();
      ctx.moveTo(0, py);
      ctx.lineTo(width, py);
      ctx.stroke();
      ctx.fillText(label, 8, Math.max(10, py - 3));
    };

    ctx.save();
    ctx.font = "10px ui-monospace, monospace";
    let work = 0;
    if (profile && visibleCoordinate(profile.source.coordinate)) {
      const rows = profile.profile.rows;
      const max = rows.reduce((peak, row) => Math.max(peak, row.volume_units), 0);
      const panelWidth = Math.min(width * .25, 210);
      ctx.globalAlpha = settings.opacity;
      for (const row of rows) {
        if (!row.volume_units) continue;
        const bottom = tick(row.low_tick - .5), top = tick(row.high_tick + .5);
        if (top === null || bottom === null || bottom < 0 || top > height) continue;
        const size = row.volume_units / max * panelWidth;
        const value = profile.profile.value;
        ctx.fillStyle = value && row.low_tick >= value.val_tick && row.high_tick <= value.vah_tick ? settings.color : "#627487";
        ctx.fillRect(width - size, top, size, Math.max(1, bottom - top));
        work++;
      }
      ctx.globalAlpha = .85;
      for (const [kind, color] of [["hvn", settings.color], ["lvn", "#92a4b6"]] as const) {
        ctx.fillStyle = color;
        for (const row of profile.profile.nodes[kind]) {
          const py = tick((row.low_tick + row.high_tick) / 2);
          if (py !== null && py >= 0 && py <= height) {
            ctx.fillRect(width - 4, py - 1, 3, 2);
            work++;
          }
        }
      }
      levels(profile.profile.value, settings.color, ["POC", "VAH", "VAL"]);
      ctx.globalAlpha = 1;
    }
    if (tpo && visibleCoordinate(tpo.source.coordinate)) {
      const balance = tpo.tpo.initial_balance[0];
      ctx.globalAlpha = .7;
      if (balance?.high_tick != null && balance.low_tick != null) {
        reference(balance.high_tick, settings.tpoColor, "IB high");
        reference(balance.low_tick, settings.tpoColor, "IB low");
      }
      const periods = tpo.tpo.periods;
      const column = Math.min(13, width * .43 / Math.max(1, periods.length));
      const offset = profile ? Math.min(width * .25, 210) : 0;
      ctx.fillStyle = settings.tpoColor;
      for (const period of periods) {
        const px = width - offset - (periods.length - period.index) * column;
        ctx.globalAlpha = period.partial ? .48 : .82;
        for (const [low, high] of period.ranges ?? []) {
          const bottom = tick(low - .5), top = tick(high + .5);
          if (top === null || bottom === null || bottom < 0 || top > height) continue;
          if (!period.letter || column < 8 || bottom - top < 8) {
            ctx.fillRect(px, top, Math.max(1, column - 1), Math.max(1, bottom - top));
            work++;
          } else {
            const step = tpo.tpo.row_ticks;
            const first = low + Math.max(0, Math.floor((bottom - height) / (bottom - top) * ((high - low + 1) / step))) * step;
            for (let row = first; row <= high && work < 12000; row += step) {
              const py = tick(row + (step - 1) / 2);
              if (py === null || py < 0) break;
              if (py <= height) {
                ctx.fillText(period.letter, px, py + 3);
                work++;
              }
            }
          }
        }
      }
    }
    if (context && settings.prior && visibleCoordinate(context.source.coordinate)) {
      ctx.globalAlpha = .7;
      levels(context.previous.value, "#dba1ec", ["Prior POC", "Prior VAH", "Prior VAL"]);
    }

    if (vwap) {
      ctx.setLineDash([]);
      ctx.strokeStyle = ctx.fillStyle = settings.vwapColor;
      const first = lowerBound(points, from, point => point.candle);
      const last = lowerBound(points, to + 1, point => point.candle);
      const stride = Math.max(1, Math.floor((last - first) / Math.max(1, width)));
      const fields: ("vwap" | "upper" | "lower")[] = settings.bands ? ["vwap", "upper", "lower"] : ["vwap"];
      for (const field of fields) {
        ctx.globalAlpha = field === "vwap" ? 1 : .45;
        ctx.beginPath();
        let run = -1;
        for (let i = first; i < last; i += stride) {
          const point = points[i], value = point[field];
          if (value === null) continue;
          const px = x(point.candle), py = y(value);
          if (px === null || py === null) continue;
          if (run !== point.run) {
            ctx.moveTo(px, py);
            ctx.lineTo(px + 1.25, py);
            ctx.moveTo(px, py);
          } else ctx.lineTo(px, py);
          run = point.run;
          work++;
        }
        ctx.stroke();
      }
      if (anchor && vwap.source.coordinate) {
        const index = lowerBound(bars, anchor.time + 1, bar => bar.time) - 1;
        const bar = bars[index];
        const px = bar && anchor.time < bar.available_at && matchesCoordinate(bar, vwap.source.coordinate, data.contract)
          ? x(bar.time) : null;
        const py = y(anchor.price);
        if (px !== null && py !== null) {
          ctx.globalAlpha = 1;
          ctx.fillRect(px - 3, py - 3, 6, 6);
        }
      }
    }
    ctx.restore();
    if (benchmark)
      performance.measure("nq-amt-primitives", { start: started, detail: { work } });
  });
}

export default function AuctionOverlay(props: Props) {
  const { chart, series, profile, tpo, vwap, context, data } = props;
  const enabled = Boolean(profile || tpo || vwap || (context && props.settings.prior));
  const points = useMemo(() => vwap?.source.coordinate && data ?
    plotPoints(data.bars, vwap.vwap.points, vwap.source.coordinate, data.contract) : [], [data, vwap]);
  const render = useMemo(() => paint(props, points), [props, points]);
  const draw = useRef(render);
  const redraw = useRef<() => void>(null);
  useLayoutEffect(() => {
    if (!enabled) return;
    const views = [{ renderer: () => ({ draw: (...args: Parameters<typeof render>) => draw.current(...args) }) }];
    const primitive: ISeriesPrimitive = {
      paneViews: () => views,
      attached: ({ requestUpdate }) => { redraw.current = requestUpdate; },
      detached: () => { redraw.current = null; },
    };
    series.attachPrimitive(primitive);
    return () => series.detachPrimitive(primitive);
  }, [chart, series, enabled]);
  useLayoutEffect(() => {
    draw.current = render;
    redraw.current?.();
  }, [render]);
  return null;
}
