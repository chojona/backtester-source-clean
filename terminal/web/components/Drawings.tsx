"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {createPortal} from "react-dom";
import { Crosshair, Minus, MoveUpRight, Spline, Square, ListTree, Ruler } from "lucide-react";
import {
  IChartApi,
  ISeriesApi,
  UTCTimestamp,
  Logical,
} from "lightweight-charts";
import type { Snapshot, Bar } from "@/lib/types";
import type { SeriesIdentity } from "@/lib/chartWindow";
import {
  Indicators,
  Anchor,
  Drawing,
  readDrawings,
  writeDrawings,
  visibleDrawings,
  project,
} from "@/lib/workspace";
const UNDO_LIMIT = 50;
const drawingTools = [
  { id: "select", label: "Select / pan", Icon: Crosshair },
  { id: "horizontal", label: "Horizontal level", Icon: Minus },
  { id: "ray", label: "Ray", Icon: MoveUpRight },
  { id: "trendline", label: "Trendline", Icon: Spline },
  { id: "rectangle", label: "Rectangle", Icon: Square },
  { id: "fibonacci", label: "Fibonacci", Icon: ListTree },
  { id: "range", label: "Price range", Icon: Ruler },
];

export default function Drawings({
  chart,
  series,
  data,
  settings,
  toolbarTarget,
  railTarget,
  chartSeries,
  replay,
}: {
  chart: IChartApi;
  series: ISeriesApi<"Candlestick">;
  data: Snapshot | null;
  settings: Indicators;
  toolbarTarget?: HTMLElement|null;
  railTarget?: HTMLElement|null;
  chartSeries?: SeriesIdentity;
  replay: boolean;
}) {
  const [stored, setStored] = useState<{ key: string; drawings: Drawing[] }>({ key: "", drawings: [] }),
    [tool, setTool] = useState("select"),
    [selected, setSelected] = useState(""),
    [pending, setPending] = useState<Anchor | null>(null),
    [size, setSize] = useState({ width: 0, height: 0 }),
    [, tick] = useState(0),
    [warning, setWarning] = useState("");
  const svg = useRef<SVGSVGElement>(null),
    drag = useRef<{ id: string; index: number; changed: boolean } | null>(null);
  const undoHistory = useRef<{ scope: string; entries: { drawings: Drawing[]; asOf: number }[] }>({
    scope: "", entries: [],
  });
  const adjusted = data?.contract === "NQ1! Adjusted";
  const key = data && chartSeries
    ? "nq:v3:drawings:" + JSON.stringify([data.contract, data.display, chartSeries.release_id,
        chartSeries.build_id, chartSeries.artifact_id])
    : "";
  const objects = key && stored.key === key ? stored.drawings : [];
  const asOf = data ? Date.parse(data.as_of) / 1000 : -Infinity;
  const undoScope = key && data ? JSON.stringify([key, data.session, replay]) : "";
  useLayoutEffect(() => {
    if (undoScope && undoScope !== undoHistory.current.scope)
      undoHistory.current = { scope: undoScope, entries: [] };
  }, [undoScope]);
  useLayoutEffect(() => {
    if (!key || !data || stored.key === key) return;
    const legacy = adjusted ? null : "nq:v2:drawings:" + data.contract + ":";
    setStored({ key, drawings: readDrawings(key, legacy, data.display) });
    setSelected("");
    setPending(null);
    drag.current = null;
  }, [key, data, adjusted, stored.key]);
  useLayoutEffect(() => {
    setPending(null);
    setSelected("");
    drag.current = null;
  }, [replay, data?.session, data?.timeframe]);
  const save = (next: Drawing[]) => {
    setStored({ key, drawings: next });
    if (!writeDrawings(key, next))
      setWarning("Local storage unavailable; drawings last for this visit.");
  };
  const update = (next: Drawing[], recordUndo = true) => {
    if (!undoScope || stored.key !== key) return;
    if (recordUndo) {
      const entries = undoHistory.current.entries;
      entries.push({ drawings: objects, asOf });
      if (entries.length > UNDO_LIMIT) entries.shift();
    }
    save(next);
  };
  useEffect(() => {
    let frame = 0;
    const redraw = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const { width, height } = chart.paneSize(0);
        setSize(current => current.width === width && current.height === height ? current : { width, height });
        tick((t) => t + 1);
      });
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(redraw);
    const host = svg.current?.parentElement;
    const observer = new ResizeObserver(redraw);
    const pane = series.getPane().getHTMLElement();
    if (pane) observer.observe(pane);
    if (host) {
      observer.observe(host);
      host.addEventListener("pointermove", redraw);
      host.addEventListener("wheel", redraw);
    }
    redraw();
    return () => {
      cancelAnimationFrame(frame);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(redraw);
      observer.disconnect();
      host?.removeEventListener("pointermove", redraw);
      host?.removeEventListener("wheel", redraw);
    };
  }, [chart, data, series]);
  const bars = data?.bars || [];
  const indexAfter = (time: number) => {
    let left = 0, right = bars.length;
    while (left < right) {
      const middle = Math.floor((left + right) / 2);
      if (bars[middle].time <= time) left = middle + 1;
      else right = middle;
    }
    return left;
  };
  const barAt = (time: number): Bar | undefined => {
    const bar = bars[indexAfter(time) - 1];
    return bar && time < bar.available_at ? bar : undefined;
  };
  const timeX = (t: number) => {
    const ts = chart.timeScale(), exact = ts.timeToCoordinate(t as UTCTimestamp);
    if (exact !== null) return exact;
    const i = indexAfter(t);
    const a = bars[i - 1], b = bars[i];
    if (!a || t >= a.available_at) return null;
    const first = ts.timeToIndex(a.time as UTCTimestamp);
    const second = b && ts.timeToIndex(b.time as UTCTimestamp);
    if (first === null) return null;
    return ts.logicalToCoordinate((first + (second == null ? 0 :
      (second - first) * (t - a.time) / (b.time - a.time))) as Logical);
  };
  const point = (e: React.PointerEvent): Anchor | null => {
    const r = svg.current!.getBoundingClientRect(),
      x = e.clientX - r.left,
      y = e.clientY - r.top;
    const { width, height } = chart.paneSize(0);
    if (x < 0 || x >= width || y < 0 || y >= height) return null;
    const time = chart.timeScale().coordinateToTime(x),
      price = series.coordinateToPrice(y);
    if (typeof time !== "number" || price === null || !barAt(time) || (replay && time > asOf)) return null;
    return { time, price: Math.round(price * 100) / 100 };
  };
  const sameBlock = (points: [Anchor, Anchor], block: number | undefined) =>
    !adjusted || block !== undefined && points.every(anchor => barAt(anchor.time)?.adjustment_block_id === block);
  const visible = (replay ? visibleDrawings(objects, asOf) : data ? objects : []).filter(
    drawing => sameBlock(drawing.points, drawing.adjustmentBlock)),
    active = visible.find((d) => d.id === selected);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (event.defaultPrevented || event.isComposing ||
          (target instanceof HTMLElement &&
            (target.isContentEditable || target.closest("input, select, textarea, dialog")))) return;

      if ((event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey &&
          event.key.toLowerCase() === "z" && undoScope) {
        if (pending) {
          event.preventDefault();
          setPending(null);
          return;
        }
        const entry = undoHistory.current.entries.at(-1);
        if (!entry || (replay && entry.asOf > asOf)) return;
        event.preventDefault();
        undoHistory.current.entries.pop();
        drag.current = null;
        save(entry.drawings);
        setSelected("");
        return;
      }
      if (event.key === "Escape") {
        setPending(null);
        setTool("select");
        setSelected("");
      }
      if ((event.key === "Delete" || event.key === "Backspace") && active) {
        event.preventDefault();
        update(objects.filter(drawing => drawing.id !== active.id));
        setSelected("");
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  });

  const selectTool = (next: string) => {
    setTool(next);
    setPending(null);
  };
  const toolbar = (
      <div className="drawing-toolbar">
        <select
          aria-label="Drawing tool"
          value={tool}
          onChange={(e) => selectTool(e.target.value)}
        >
          {drawingTools.map(({ id, label }) => <option key={id} value={id}>{label}</option>)}
        </select>
        <details>
          <summary>Objects ({visible.length})</summary>
          <div className="drawing-objects">
            {visible.map((d) => (
              <div key={d.id}>
                <button
                  aria-pressed={selected === d.id}
                  onClick={() => setSelected(d.id)}
                >
                  {d.type}
                </button>
                <button
                  aria-label={"Toggle " + d.type}
                  onClick={() =>
                    update(
                      objects.map((x) =>
                        x.id === d.id ? { ...x, visible: !x.visible } : x,
                      ),
                    )
                  }
                >
                  {d.visible ? "Hide" : "Show"}
                </button>
                <button
                  aria-label={"Delete " + d.type}
                  onClick={() => update(objects.filter((x) => x.id !== d.id))}
                >
                  Delete
                </button>
              </div>
            ))}
            {active && (
              <div className="anchor-editor">
                {active.points.map((p, i) => (
                  <label key={i}>
                    Anchor {i + 1}
                    <input
                      aria-label={"Anchor " + (i + 1) + " UTC time"}
                      type="datetime-local"
                      value={new Date(p.time * 1000).toISOString().slice(0, 16)}
                      onChange={(e) => {
                        const time = Date.parse(e.target.value + "Z") / 1000;
                        if (!Number.isFinite(time) || time === p.time || (replay && time > asOf)) return;
                        const points = active.points.map((anchor, j) => j === i ? { ...anchor, time } : anchor) as [Anchor, Anchor];
                        if (!sameBlock(points, active.adjustmentBlock)) return;
                        update(
                          objects.map((d) =>
                            d.id === active.id
                              ? {
                                  ...d,
                                  points,
                                }
                              : d,
                          ),
                        );
                      }}
                    />
                    <input
                      aria-label={"Anchor " + (i + 1) + " price"}
                      type="number"
                      step=".25"
                      value={p.price}
                      onChange={(e) => {
                        if (!Number.isFinite(+e.target.value) || +e.target.value === p.price) return;
                        update(
                          objects.map((d) =>
                            d.id === active.id
                              ? {
                                  ...d,
                                  points: d.points.map((a, j) =>
                                    j === i
                                      ? { ...a, price: +e.target.value }
                                      : a,
                                  ) as [Anchor, Anchor],
                                }
                              : d,
                          ),
                        );
                      }}
                    />
                  </label>
                ))}
              </div>
            )}
          </div>
        </details>
        {pending && <span>Click second anchor · Esc cancels</span>}
        {warning && <span role="status">{warning}</span>}
      </div>
  );
  return (
    <>
      {toolbarTarget ? createPortal(toolbar, toolbarTarget) : toolbar}
      {railTarget && createPortal(
        <div className="drawing-rail-buttons" role="group" aria-label="Drawing shortcuts">
          {drawingTools.map(({ id, label, Icon }) =>
            <button key={id} type="button" title={label} aria-label={label}
              aria-pressed={tool === id} onClick={() => selectTool(id)}>
              <Icon size={18} strokeWidth={1.5} />
            </button>)}
        </div>, railTarget)}
      <svg
        ref={svg}
        style={{ width: size.width, height: size.height }}
        className={
          "drawing-layer " +
          (tool !== "select" || drag.current ? "placing" : "")
        }
        onPointerDown={(e) => {
          if (tool === "select") return;
          const p = point(e);
          if (!p) return;
          e.preventDefault();
          if (!pending && !["horizontal", "ray"].includes(tool)) {
            setPending(p);
            return;
          }
          const points: [Anchor, Anchor] = [pending || p, p];
          const adjustmentBlock = adjusted ? barAt(p.time)?.adjustment_block_id : undefined;
          if (!sameBlock(points, adjustmentBlock)) return;
          const d: Drawing = {
            id: crypto.randomUUID(),
            type: tool as Drawing["type"],
            points,
            adjustmentBlock,
            createdAt: asOf,
            visible: true,
            color: "#8bb8f4",
          };
          update([...objects, d]);
          setPending(null);
          setSelected(d.id);
          setTool("select");
        }}
        onPointerMove={(e) => {
          const gesture = drag.current;
          if (!gesture) return;
          const p = point(e);
          const drawing = visible.find(d => d.id === gesture.id);
          if (!p || !drawing || (adjusted && barAt(p.time)?.adjustment_block_id !== drawing.adjustmentBlock)) return;
          const previous = drawing.points[gesture.index];
          if (previous.time === p.time && previous.price === p.price) return;
          const points = [...drawing.points] as [Anchor, Anchor];
          points[gesture.index] = p;
          // A drag may emit many pointer events. Its first change records the original drawing.
          update(objects.map(d => d.id === gesture.id ? { ...d, points } : d), !gesture.changed);
          gesture.changed = true;
        }}
        onPointerUp={() => {
          drag.current = null;
          tick((t) => t + 1);
        }}
        onPointerCancel={() => {
          drag.current = null;
          tick((t) => t + 1);
        }}
      >
        <defs>
          <clipPath id="drawing-price-clip">
            <rect
              width={size.width}
              height={size.height}
            />
          </clipPath>
        </defs>
        <g clipPath="url(#drawing-price-clip)">
          {settings.boundaries.visible &&
            data?.boundaries
              .filter((t) => t <= asOf)
              .map((t) => {
                const x = timeX(t);
                return x === null ? null : (
                  <line
                    key={t}
                    x1={x}
                    x2={x}
                    y1="0"
                    y2={size.height}
                    stroke={settings.boundaries.color}
                    strokeDasharray={
                      settings.boundaries.style === 1
                        ? "1 3"
                        : settings.boundaries.style === 2
                          ? "4 4"
                          : undefined
                    }
                  />
                );
              })}
          {visible
            .filter((d) => d.visible)
            .map((d) => {
              const coords = project(d, timeX, (p) =>
                series.priceToCoordinate(p),
              );
              if (coords.some((p) => p.x === null || p.y === null)) return null;
              const [a, b] = coords as { x: number; y: number }[],
                line = (y: number, k: number | string = 0) => (
                  <line key={k} x1={a.x} x2={b.x} y1={y} y2={y} />
                );
              return (
                <g
                  key={d.id}
                  stroke={d.color}
                  strokeWidth={selected === d.id ? 2.5 : 1.5}
                  fill="none"
                  className="drawing-object"
                  onPointerDown={(e) => {
                    if (tool === "select") {
                      e.stopPropagation();
                      setSelected(d.id);
                    }
                  }}
                >
                  {d.type === "horizontal" ? (
                    <line x1="0" x2={size.width} y1={a.y} y2={a.y} />
                  ) : d.type === "ray" ? (
                    <line x1={a.x} x2={size.width} y1={a.y} y2={a.y} />
                  ) : d.type === "trendline" ? (
                    <line x1={a.x} x2={b.x} y1={a.y} y2={b.y} />
                  ) : d.type === "fibonacci" ? (
                    [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1].map((r) => (
                      <g key={r}>
                        {line(a.y + (b.y - a.y) * r, r)}
                        <text
                          x={Math.min(a.x, b.x) + 4}
                          y={a.y + (b.y - a.y) * r - 3}
                          fill={d.color}
                          stroke="none"
                          fontSize="10"
                        >
                          {r} ·{" "}
                          {(
                            d.points[0].price +
                            (d.points[1].price - d.points[0].price) * r
                          ).toFixed(2)}
                        </text>
                      </g>
                    ))
                  ) : (
                    <>
                      <rect
                        x={Math.min(a.x, b.x)}
                        y={Math.min(a.y, b.y)}
                        width={Math.abs(a.x - b.x)}
                        height={Math.abs(a.y - b.y)}
                        fill="#7198c91a"
                      />
                      {d.type === "range" && (
                        <text
                          x={Math.min(a.x, b.x) + 4}
                          y={Math.min(a.y, b.y) + 15}
                          fill={d.color}
                          stroke="none"
                          fontSize="12"
                        >
                          {(d.points[1].price - d.points[0].price).toFixed(2)}{" "}
                          pts ·{" "}
                          {(
                            (d.points[1].price / d.points[0].price - 1) *
                            100
                          ).toFixed(2)}
                          %
                        </text>
                      )}
                    </>
                  )}
                  {selected === d.id &&
                    coords.map((p, i) => (
                      <circle
                        key={i}
                        cx={p.x!}
                        cy={p.y!}
                        r="5"
                        fill="#0c1119"
                        onPointerDown={(e) => {
                          if (tool !== "select") return;
                          e.stopPropagation();
                          drag.current = { id: d.id, index: i, changed: false };
                          svg.current!.setPointerCapture(e.pointerId);
                          tick((t) => t + 1);
                        }}
                      />
                    ))}
                </g>
              );
            })}
          {pending && (
            <circle
              cx={timeX(pending.time) ?? 0}
              cy={series.priceToCoordinate(pending.price) ?? 0}
              r="4"
              fill="#deb568"
            />
          )}
        </g>
      </svg>
    </>
  );
}
