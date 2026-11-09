"use client";
import { useEffect, useRef, useState } from "react";
import {createPortal} from "react-dom";
import {
  IChartApi,
  ISeriesApi,
  UTCTimestamp,
  Logical,
} from "lightweight-charts";
import { Snapshot } from "@/lib/types";
import {
  Indicators,
  Anchor,
  Drawing,
  readLocal,
  writeLocal,
  validDrawing,
  visibleDrawings,
  project,
} from "@/lib/workspace";
export default function Drawings({
  chart,
  series,
  data,
  settings,
  toolbarTarget,
}: {
  chart: IChartApi;
  series: ISeriesApi<"Candlestick">;
  data: Snapshot | null;
  settings: Indicators;
  toolbarTarget?: HTMLElement|null;
}) {
  const [objects, setObjects] = useState<Drawing[]>([]),
    [tool, setTool] = useState("select"),
    [selected, setSelected] = useState(""),
    [pending, setPending] = useState<Anchor | null>(null),
    [size, setSize] = useState({ width: 0, height: 0 }),
    [, tick] = useState(0),
    [warning, setWarning] = useState("");
  const svg = useRef<SVGSVGElement>(null),
    drag = useRef<{ id: string; index: number } | null>(null);
  const key = data
    ? `nq:v2:drawings:${data.contract}:${data.session}:${data.display || "Globex"}`
    : "";
  const asOf = data ? Date.parse(data.as_of) / 1000 : -Infinity;
  useEffect(() => {
    const raw = readLocal<Drawing[]>(key, []);
    setObjects(Array.isArray(raw) ? raw.filter(validDrawing) : []);
    setSelected("");
    setPending(null);
  }, [key]);
  const update = (next: Drawing[]) => {
    setObjects(next);
    if (key && !writeLocal(key, next))
      setWarning("Local storage unavailable; drawings last for this visit.");
  };
  useEffect(() => {
    let frame = 0;
    const redraw = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const r = svg.current?.getBoundingClientRect();
        if (r) setSize({ width: r.width, height: r.height });
        tick((t) => t + 1);
      });
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(redraw);
    const host = svg.current?.parentElement;
    const observer = new ResizeObserver(redraw);
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
  }, [chart, data]);
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      if (/INPUT|SELECT|TEXTAREA/.test((e.target as HTMLElement).tagName))
        return;
      if (e.key === "Escape") {
        setPending(null);
        setTool("select");
        setSelected("");
      }
      if ((e.key === "Delete" || e.key === "Backspace") && selected) {
        e.preventDefault();
        update(objects.filter((d) => d.id !== selected));
        setSelected("");
      }
    };
    document.addEventListener("keydown", fn);
    return () => document.removeEventListener("keydown", fn);
  });
  const bars = data?.bars || [];
  const timeX = (t: number) => {
    const ts = chart.timeScale(),
      exact = ts.timeToCoordinate(t as UTCTimestamp);
    if (exact !== null) return exact;
    if (!bars.length) return null;
    let i = bars.findIndex((b) => b.time > t);
    if (i < 0) i = bars.length;
    const left = Math.max(0, Math.min(bars.length - 2, i - 1)),
      a = bars[left],
      b = bars[left + 1];
    return ts.logicalToCoordinate(
      (left + (t - a.time) / (b ? b.time - a.time : 60)) as Logical,
    );
  };
  const point = (e: React.PointerEvent): Anchor | null => {
    const r = svg.current!.getBoundingClientRect(),
      x = e.clientX - r.left,
      y = e.clientY - r.top;
    if (x > r.width - 60 || y > r.height * 0.8) return null;
    const logical = chart.timeScale().coordinateToLogical(x),
      price = series.coordinateToPrice(y);
    if (logical === null || price === null || !bars.length) return null;
    const b = bars[Math.max(0, Math.min(bars.length - 1, Math.round(logical)))];
    return { time: b.time, price: Math.round(price * 100) / 100 };
  };
  const visible = visibleDrawings(objects, asOf),
    active = visible.find((d) => d.id === selected);
  const toolbar = (
<div className="drawing-toolbar">
        <select
          aria-label="Drawing tool"
          value={tool}
          onChange={(e) => {
            setTool(e.target.value);
            setPending(null);
          }}
        >
          <option value="select">Select / pan</option>
          {[
            "horizontal",
            "ray",
            "trendline",
            "rectangle",
            "fibonacci",
            "range",
          ].map((t) => (
            <option key={t}>{t}</option>
          ))}
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
                        if (!Number.isFinite(time) || time > asOf) return;
                        update(
                          objects.map((d) =>
                            d.id === active.id
                              ? {
                                  ...d,
                                  points: d.points.map((a, j) =>
                                    j === i ? { ...a, time } : a,
                                  ) as [Anchor, Anchor],
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
                        if (!Number.isFinite(+e.target.value)) return;
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
      {toolbarTarget ? createPortal(toolbar,toolbarTarget) : toolbar}
      <svg
        ref={svg}
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
          const d: Drawing = {
            id: crypto.randomUUID(),
            type: tool as Drawing["type"],
            points: [pending || p, p],
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
          if (!drag.current) return;
          const p = point(e);
          if (p)
            update(
              objects.map((d) =>
                d.id === drag.current!.id
                  ? {
                      ...d,
                      points: d.points.map((a, i) =>
                        i === drag.current!.index ? p : a,
                      ) as [Anchor, Anchor],
                    }
                  : d,
              ),
            );
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
              width={Math.max(0, size.width - 60)}
              height={size.height * 0.8}
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
                    y2={size.height * 0.8}
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
                    <line x1="0" x2={size.width - 60} y1={a.y} y2={a.y} />
                  ) : d.type === "ray" ? (
                    <line x1={a.x} x2={size.width - 60} y1={a.y} y2={a.y} />
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
                          drag.current = { id: d.id, index: i };
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
