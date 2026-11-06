"use client";
import { useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  LockKeyhole,
  Search,
  Table2,
  FlaskConical,
  ChartNoAxesCombined,
  History,
} from "lucide-react";
import { Snapshot, fmt, clock } from "@/lib/types";
const tabs = [
  { name: "Data Explorer", icon: Table2 },
  { name: "Strategy Research", icon: FlaskConical },
  { name: "Backtest Results", icon: ChartNoAxesCombined },
  { name: "Experiment History", icon: History },
];
export default function Explorer({
  data,
  offset,
  setOffset,
}: {
  data: Snapshot | null;
  offset: number;
  setOffset: (v: number) => void;
}) {
  const [tab, setTab] = useState("Data Explorer");
  const [search, setSearch] = useState("");
  const rows =
    data?.explorer.rows.filter(
      (b) =>
        !search ||
        `${clock(b.time)} ${b.open} ${b.high} ${b.low} ${b.close}`.includes(
          search,
        ),
    ) ?? [];
  return (
    <section className="workspace">
      <div
        className="workspace-tabs"
        role="tablist"
        aria-label="Research workspace"
      >
        {tabs.map((t) => (
          <button
            key={t.name}
            role="tab"
            aria-selected={tab === t.name}
            onClick={() => setTab(t.name)}
            className={tab === t.name ? "active" : ""}
          >
            <t.icon size={14} />
            {t.name}
            {t.name !== "Data Explorer" && <LockKeyhole size={10} />}
          </button>
        ))}
        <span className="workspace-label">WORKSPACE / 01</span>
      </div>
      {tab !== "Data Explorer" ? (
        <div className="inactive-panel">
          <LockKeyhole size={24} />
          <h3>{tab}</h3>
          <p>
            Inactive in v0.2. No {tab.toLowerCase()} functionality is connected.
          </p>
          <button onClick={() => setTab("Data Explorer")}>
            Return to Data Explorer
          </button>
        </div>
      ) : (
        <>
          <div className="explorer-toolbar">
            <div>
              <b>Observed OHLCV</b>
              <span>
                {data?.contract || "—"} <i>/</i> {data?.timeframe || "1m"}{" "}
                <i>/</i> {data?.session || "Select a session"}
              </span>
              <span className="tag">ELIGIBLE ONLY</span>
            </div>
            <label className="search">
              <Search size={13} />
              <input
                aria-label="Filter current data page"
                placeholder="Filter this page…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>TIME (ET)</th>
                  <th>OPEN</th>
                  <th>HIGH</th>
                  <th>LOW</th>
                  <th>CLOSE</th>
                  <th>VOLUME</th>
                  <th>VWAP</th>
                  <th>SOURCE 1m</th>
                  <th>STATUS</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((b) => (
                  <tr key={b.time}>
                    <td>
                      {clock(b.time)}
                      <span className="cell-date">
                        {new Date(b.time * 1000).toLocaleDateString("en-CA", {
                          timeZone: "America/New_York",
                        })}
                      </span>
                    </td>
                    <td>{fmt(b.open)}</td>
                    <td>{fmt(b.high)}</td>
                    <td>{fmt(b.low)}</td>
                    <td className={b.close >= b.open ? "teal" : "red"}>
                      {fmt(b.close)}
                    </td>
                    <td>{fmt(b.volume, 0)}</td>
                    <td className="gold-text">{fmt(b.vwap)}</td>
                    <td>{b.source_count}</td>
                    <td>
                      <span
                        className={`row-status ${b.partial ? "partial" : ""}`}
                      >
                        <i />
                        {b.partial ? "DEVELOPING" : "OBSERVED"}
                      </span>
                    </td>
                  </tr>
                ))}
                {!rows.length && (
                  <tr>
                    <td colSpan={9} className="empty-cell">
                      {data
                        ? "No observed bars match this page."
                        : "Waiting for eligible session data."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="table-footer">
            <span>
              {data
                ? `${offset + 1}–${Math.min(offset + 50, data.explorer.total)} of ${data.explorer.total} visible candles`
                : "0 visible candles"}{" "}
              <i>·</i> No missing bars filled
            </span>
            <div>
              <button
                aria-label="Previous data page"
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 50))}
              >
                <ChevronLeft size={14} />
              </button>
              <span>Page {Math.floor(offset / 50) + 1}</span>
              <button
                aria-label="Next data page"
                disabled={!data || offset + 50 >= data.explorer.total}
                onClick={() => setOffset(offset + 50)}
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
