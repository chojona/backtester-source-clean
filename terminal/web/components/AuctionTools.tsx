"use client";
import { memo, useEffect, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import type { IChartApi, ISeriesApi, MouseEventParams, Time } from "lightweight-charts";
import { scopes, useAmtResult, useAmtSettings, validDate, vwapScopes,
  type AmtSettings, type Context, type Envelope, type Profile, type Tpo, type Vwap } from "@/lib/amt";
import type { SeriesIdentity } from "@/lib/chartWindow";
import { fmt, type Snapshot } from "@/lib/types";
import AuctionOverlay from "./AuctionOverlay";

function price(tick: number | null | undefined) {
  return fmt(tick == null ? null : tick * .25);
}
const et = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", dateStyle: "medium", timeStyle: "long",
});

function Provenance({ result }: { result: Envelope }) {
  return <details className="auction-provenance">
    <summary>{result.scope} · {result.coverage.observed_minutes.toLocaleString()} observed minutes</summary>
    <div>{result.start} → {result.end} · {result.methodology_version}</div>
    <div>Cutoff {et.format(new Date(result.cutoff.as_of))} · observation close</div>
    <div>Historical publication unverified · {result.source.admission}</div>
    <div>{result.coverage.all_declared_sessions_complete ? "Declared grids reconciled" : result.coverage.status.replaceAll("_", " ") + " · coverage incomplete"}
      {result.source.retrospective_prices && " · retrospective prices"}</div>
    <div>{result.coverage.quality.interval_count} reviewed gap intervals
      {result.coverage.quality.unresolved_roll_ids?.length ? " · unresolved roll in scope" : ""}</div>
    {result.coverage.sessions.map(s => <div key={s.trading_date}>
      {s.trading_date} · {s.lineage?.source_contract ?? "—"} · {s.status.replaceAll("_", " ")} · {s.observed_minutes}/{s.elapsed_expected_minutes ?? "—"}m
      {s.lineage?.adjustment_block_id != null && ` · block ${s.lineage.adjustment_block_id}, offset ${s.lineage.adjustment_offset}`}
    </div>)}
    <dl>{Object.entries(result.source.files).map(([name, hash]) => <div key={name}><dt>{name}</dt><dd>{hash}</dd></div>)}</dl>
  </details>;
}

function AuctionTools({ chart, series, selected, data, identity, replay, target }: {
  chart: IChartApi; series: ISeriesApi<"Candlestick">; selected: Snapshot | null; data: Snapshot | null;
  identity?: SeriesIdentity; replay: boolean; target: HTMLDivElement | null;
}) {
  const [open, setOpen] = useState(false);
  const [picking, setPicking] = useState("");
  const [anchorError, setAnchorError] = useState("");
  const adjusted = selected?.contract === "NQ1! Adjusted";
  const block = adjusted ? selected?.bars.at(-1)?.adjustment_block_id : undefined;
  const key = identity && selected && (!adjusted || block != null)
    ? "nq:v3:amt:" + JSON.stringify([identity.release_id, identity.build_id, identity.artifact_id,
      selected.contract, selected.display, block ?? null]) : "";
  const { settings, update } = useAmtSettings(key);
  const cutoff = selected && replay ? Date.parse(selected.as_of) / 1000 : Infinity;
  const anchor = settings.anchor && settings.anchor.availableAt <= cutoff ? settings.anchor : null;
  const pickingHere = !!key && picking === key;
  const day = selected?.session ?? "";
  const start = settings.start || day;
  const end = settings.end || day;
  const validRange = settings.scope !== "range" || (validDate(start) && validDate(end) && start <= end &&
    (Date.parse(end) - Date.parse(start)) / 86400000 < 31);
  const makeQuery = (scope: string, extra: Record<string, string>) => {
    if (!selected || !key || (adjusted && replay)) return "";
    const q = new URLSearchParams({ contract: selected.contract, session: selected.session, display: selected.display,
      scope, ...extra });
    if (scope === "range") {
      if (!validRange) return "";
      q.set("start", start);
      q.set("end", end);
    }
    if (replay) {
      q.set("replay", "true");
      q.set("as_of", selected.as_of);
    }
    return q.toString();
  };
  const allocation = { method: settings.method, row_ticks: String(settings.width) };
  const profile = useAmtResult<Profile>("profile", settings.profile ?
    makeQuery(settings.scope, { ...allocation, sensitivity: "true" }) : "", selected, identity, replay);
  const tpo = useAmtResult<Tpo>("tpo", settings.tpo !== "off" ?
    makeQuery("session", { row_ticks: String(settings.width), period_minutes: String(settings.period),
      representation: settings.tpo }) : "", selected, identity, replay);
  const context = useAmtResult<Context>("context", settings.prior || open ?
    makeQuery(settings.scope, allocation) : "", selected, identity, replay);
  const vwap = useAmtResult<Vwap>("vwap", settings.vwap !== "off" && (settings.vwap !== "manual" || anchor) ?
    makeQuery(settings.vwap, {
      deviations: String(selected?.deviations ?? 1),
      ...(settings.vwap === "manual" && anchor ? { anchor: new Date(anchor.time * 1000).toISOString() } : {}),
    }) : "", selected, identity, replay);

  useEffect(() => {
    if (!pickingHere || !data) return;
    const pick = (event: MouseEventParams<Time>) => {
      if (!event.point || typeof event.time !== "number") return;
      const bar = data.bars.find(b => b.time === event.time);
      const pickedPrice = series.coordinateToPrice(event.point.y);
      if (!bar || pickedPrice === null || bar.available_at > cutoff ||
          (adjusted && bar.adjustment_block_id !== block)) return;
      update({ anchor: { time: bar.time, price: pickedPrice, availableAt: bar.available_at }, vwap: "manual" });
      setPicking("");
      setAnchorError("");
    };
    chart.subscribeClick(pick);
    return () => chart.unsubscribeClick(pick);
  }, [chart, series, data, pickingHere, cutoff, adjusted, block, update]);

  const saveAnchor = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const input = String(form.get("utc"));
    const time = Date.parse(input) / 1000;
    const value = Number(form.get("price"));
    const availableAt = time === anchor?.time ? anchor.availableAt : Math.ceil(time / 60) * 60 + 60;
    const observedBar = data?.bars.find(b => b.time <= time && time < b.available_at);
    if (!input.endsWith("Z") || !Number.isFinite(time) || !Number.isFinite(value) || availableAt > cutoff ||
        (adjusted && observedBar?.adjustment_block_id !== block)) {
      setAnchorError("Enter a UTC timestamp ending in Z and an available price in the current block.");
      return;
    }
    update({ anchor: { time, price: value, availableAt } });
    setAnchorError("");
  };

  const balance = tpo.result?.tpo.initial_balance[0];
  const description = context.result?.context;
  const profileValue = profile.result?.profile.value;
  const nodes = profile.result?.profile.nodes;
  const tpoValue = tpo.result?.tpo.value;
  const compare = profile.result?.profile.sensitivity?.delta_ticks;
  const extension = description?.initial_balance_extension.at(-1);
  const errors = [["Profile", profile.error], ["TPO", tpo.error], ["VWAP", vwap.error], ["Context", context.error]]
    .filter(([, error]) => error);
  const available = Boolean(key && !(adjusted && replay));
  const toggle = (name: "profile" | "prior" | "bands", label: string) =>
    <label><input type="checkbox" checked={settings[name]} onChange={e => update({ [name]: e.target.checked })} /> {label}</label>;
  return <>
    {target && createPortal(<button type="button" aria-expanded={open} aria-controls="auction-tools"
      onClick={() => { setOpen(!open); setPicking(""); }}>Auction analytics</button>, target)}
    <AuctionOverlay chart={chart} series={series} data={data} settings={settings} anchor={settings.vwap === "manual" ? anchor : null}
      profile={profile.result} tpo={tpo.result} vwap={vwap.result} context={context.result} />
    {open && <aside className="auction-tools" id="auction-tools" aria-label="Auction analytics">
      <header><strong>Auction analytics</strong><button type="button" aria-label="Close auction analytics"
        onClick={() => { setOpen(false); setPicking(""); }}>×</button></header>
      <p className="auction-caption">One-minute OHLCV estimates · observation-close cutoff</p>
      {!available ? <p>Waiting for a verified session and price coordinate.</p> : <>
        {profile.result && <p data-testid="auction-profile">
          {profile.result.profile.rows.length} rows · {fmt(profile.result.profile.total_volume, 0)} allocated
          {profileValue && ` · POC ${price(profileValue.poc.low_tick)} · VAH ${price(profileValue.vah_tick)} · VAL ${price(profileValue.val_tick)}`}
          {nodes && ` · HVN ${nodes.hvn.length} · LVN ${nodes.lvn.length}`}
          {compare && ` · alternate POC Δ ${compare.poc}t`}
        </p>}
        {tpo.result && <p data-testid="auction-tpo">{tpo.result.tpo.periods.length} TPO periods
          {tpoValue && ` · POC ${price(tpoValue.poc.low_tick)} · VAH ${price(tpoValue.vah_tick)} · VAL ${price(tpoValue.val_tick)}`}
          {balance && ` · IB ${price(balance.low_tick)}–${price(balance.high_tick)} · ${balance.complete ? "complete observed grid" : balance.developing ? "developing" : "incomplete"}`}
        </p>}
        {vwap.result && <p data-testid="auction-vwap">VWAP {fmt(vwap.result.vwap.points.at(-1)?.vwap)} · HLC3 estimate</p>}
        {description && <p>Value width {fmt(description.value_width_ticks, 0)} ticks · prior overlap {fmt(
          description.previous_value_overlap == null ? null : description.previous_value_overlap * 100, 1)}%
          · POC migration {fmt(description.poc_migration_ticks, 0)} ticks · range location {fmt(
            description.observed_range.last_close_location == null ? null : description.observed_range.last_close_location * 100, 1)}%
          · IB extension ↑ {fmt(extension?.above_ticks, 0)}t ↓ {fmt(extension?.below_ticks, 0)}t
        </p>}
        <div className="auction-grid">
          {toggle("profile", "Volume Profile")}
          {toggle("prior", "Prior POC / VAH / VAL")}
          <label>Profile scope <select value={settings.scope} onChange={e => update({ scope: e.target.value as AmtSettings["scope"] })}>
            {Object.entries(scopes).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
          <label>Volume allocation <select value={settings.method} onChange={e => update({ method: e.target.value as AmtSettings["method"] })}>
            <option value="hlc3">HLC3 tick</option><option value="uniform">Uniform high–low</option></select></label>
          {settings.scope === "range" && <>
            <label>Range start <input type="date" value={start} onChange={e => update({ start: e.target.value })} /></label>
            <label>Range end <input type="date" value={end} onChange={e => update({ end: e.target.value })} /></label>
          </>}
          <label>Row size (ticks) <select value={settings.width} onChange={e => update({ width: Number(e.target.value) })}>
            {[1, 2, 4, 8, 16, 32, 64].map(n => <option key={n}>{n}</option>)}</select></label>
          <label>Profile opacity <input type="range" min=".1" max=".9" step=".05" value={settings.opacity}
            onChange={e => update({ opacity: Number(e.target.value) })} /></label>
          <label>TPO display <select value={settings.tpo} onChange={e => update({ tpo: e.target.value as AmtSettings["tpo"] })}>
            <option value="off">Off</option><option value="blocks">Blocks</option><option value="letters">Letters</option></select></label>
          <label>TPO period <select value={settings.period} onChange={e => update({ period: Number(e.target.value) })}>
            {[5, 15, 30, 60, 120].map(n => <option key={n} value={n}>{n}m</option>)}</select></label>
          <label>Advanced VWAP <select value={settings.vwap} onChange={e => update({ vwap: e.target.value as AmtSettings["vwap"] })}>
            {Object.entries(vwapScopes).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
          {toggle("bands", "VWAP deviation bands")}
          {([["color", "Profile color"], ["tpoColor", "TPO color"], ["vwapColor", "VWAP color"]] as const).map(([name, label]) =>
            <label key={name}>{label} <input type="color" value={settings[name]} onChange={e => update({ [name]: e.target.value })} /></label>)}
        </div>
        {!validRange && <p role="alert">Choose an ordered range of up to 31 calendar dates.</p>}
        {settings.vwap === "manual" && <div className="auction-anchor">
          <button type="button" aria-pressed={pickingHere} onClick={() => setPicking(pickingHere ? "" : key)}>
            {pickingHere ? "Cancel anchor selection" : "Select anchor on chart"}</button>
          {pickingHere && <p>Choose an observed candle and a price on the chart.</p>}
          {anchor && <>
            <p data-testid="auction-anchor">Anchor {et.format(new Date(anchor.time * 1000))} · {fmt(anchor.price)}</p>
            <form key={`${anchor.time}/${anchor.price}`} onSubmit={saveAnchor}>
              <label>Anchor UTC <input name="utc" required defaultValue={new Date(anchor.time * 1000).toISOString()} /></label>
              <label>Anchor price <input name="price" required type="number" step="any" defaultValue={anchor.price} /></label>
              <button type="submit">Save anchor</button>
              <button type="button" onClick={() => update({ anchor: null })}>Clear anchor</button>
            </form>
          </>}
          {anchorError && anchor && <p role="alert">{anchorError}</p>}
        </div>}
        {[profile, tpo, context, vwap].some(result => result.loading) && <p role="status">Calculating auction estimates…</p>}
        {errors.map(([label, error]) => <p role="alert" key={label}>{label} · {error}</p>)}
        {settings.prior && context.result && !context.result.previous.value &&
          <p>Prior levels unavailable · {context.result.previous.status.replaceAll("_", " ")}</p>}
        {[profile.result, tpo.result, vwap.result, context.result].map((result, i) => result &&
          <Provenance key={i} result={result} />)}
      </>}
    </aside>}
  </>;
}

export default memo(AuctionTools);
