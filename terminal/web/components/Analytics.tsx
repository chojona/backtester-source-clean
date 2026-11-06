import { Activity, ShieldCheck, ArrowUpRight, Database } from "lucide-react";
import { Snapshot, Provenance, fmt } from "@/lib/types";
export default function Analytics({
  data,
  provenance,
}: {
  data: Snapshot | null;
  provenance: Provenance | null;
}) {
  const s = data?.stats;
  const change =
    typeof s?.close === "number" && typeof s?.open === "number"
      ? s.close - s.open
      : null;
  const metric = (
    label: string,
    value: unknown,
    suffix = "",
    className = "",
  ) => (
    <div className="metric" key={label}>
      <span>{label}</span>
      <b className={className}>
        {fmt(value, label === "Session volume" ? 0 : 2)}
        {typeof value === "number" && suffix ? <small> {suffix}</small> : null}
      </b>
    </div>
  );
  return (
    <aside className="analytics">
      <div className="panel-title">
        <Activity size={14} />
        <h2>Session analytics</h2>
        <span className="tiny-badge">AS OF</span>
      </div>
      <div className="price-block">
        <label>
          {data?.contract || "NQ"} <span>NASDAQ 100 FUTURES</span>
        </label>
        <div>
          {fmt(s?.close)}
          <ArrowUpRight
            size={22}
            className={change !== null && change < 0 ? "red" : "teal"}
          />
        </div>
        <p className={change !== null && change < 0 ? "red" : "teal"}>
          {change !== null && change >= 0 ? "+" : ""}
          {fmt(change)} <span>pts from session open</span>
        </p>
      </div>
      <section>
        <h3>SESSION OVERVIEW</h3>
        {metric("Open", s?.open)}
        {metric("High", s?.high)}
        {metric("Low", s?.low)}
        {metric("Close / last observed", s?.close)}
        <div className="range-strip">
          <i
            style={{
              width:
                typeof s?.range === "number" && s.range > 0
                  ? `${Math.max(2, Math.min(100, ((Number(s.close) - Number(s.low)) / s.range) * 100))}%`
                  : "0%",
            }}
          />
        </div>
        {metric("Current range", s?.range, "pts")}
        {metric("Session volume", s?.volume)}
      </section>
      <section>
        <h3>
          INDICATORS <Activity size={12} />
        </h3>
        {metric("Session VWAP", s?.vwap)}
        {metric(
          "VWAP deviation",
          s?.vwap_deviation,
          "pts",
          Number(s?.vwap_deviation) >= 0 ? "teal" : "red",
        )}
        {metric("Realized volatility", s?.realized_volatility, "%")}
        <p className="method">
          HLC3 VWAP approximation · 1m log-return RV, unannualized
        </p>
      </section>
      <section>
        <h3>
          OPENING RANGE{" "}
          <span>{s?.or_complete ? "COMPLETE" : "DEVELOPING"}</span>
        </h3>
        <p className="method">09:30–10:00 America/New_York</p>
        {metric("OR high", s?.or_high)}
        {metric("OR low", s?.or_low)}
        {metric("OR width", s?.or_range, "pts")}
      </section>
      <section>
        <h3>
          PREVIOUS SESSION <span>{data?.previous.date || "UNAVAILABLE"}</span>
        </h3>
        {metric("Previous high", data?.previous.high)}
        {metric("Previous low", data?.previous.low)}
      </section>
      <div className="integrity-card">
        <ShieldCheck size={17} className="teal" />
        <div>
          <b>{data ? "Research eligible" : "Awaiting dataset"}</b>
          <p>Exact contract · observed bars only</p>
        </div>
        <span className="status-dot" />
      </div>
      <div className="coverage-summary">
        <Database size={13} />
        <span>
          {fmt(provenance?.summary.eligible_sessions, 0)} eligible sessions
          <br />
          {fmt(provenance?.summary.eligible_bars, 0)} historical bars
        </span>
      </div>
      <p className="method eligibility-note">
        Retrospective QC · not strict certified. Historical publication timing
        is unproven.
      </p>
    </aside>
  );
}
