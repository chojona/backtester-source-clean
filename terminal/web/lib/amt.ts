import { useCallback, useEffect, useState } from "react";
import { sameSeries, type SeriesIdentity } from "./chartWindow";
import { api, type Bar, type Snapshot } from "./types";
import { readLocal, writeLocal, type Anchor } from "./workspace";

export const scopes = {
  session: "Selected session",
  prior_session: "Prior completed session",
  week: "Current week",
  prior_week: "Previous week",
  month: "Current month",
  prior_month: "Previous month",
  range: "Selected date range",
};
type Scope = keyof typeof scopes;
export const vwapScopes = { off: "Off", manual: "Manual anchor", session: "Session",
  week: "Current week", month: "Current month", prior_week: "Previous week", prior_month: "Previous month" };

const defaults = {
  profile: false, tpo: "off" as "off" | "blocks" | "letters", prior: false, bands: true,
  scope: "session" as Scope, vwap: "off" as keyof typeof vwapScopes, method: "hlc3" as "hlc3" | "uniform",
  width: 4, period: 30, opacity: .40, color: "#61c7ba", tpoColor: "#87aaff", vwapColor: "#edc470",
  start: "", end: "", anchor: null as (Anchor & { availableAt: number }) | null,
};
export type AmtSettings = typeof defaults;
export const validDate = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v);
const validColor = (v: unknown): v is string => typeof v === "string" && /^#[0-9a-f]{6}$/i.test(v);

function readAmt(key: string): AmtSettings {
  const saved = readLocal<{ version: number; settings: AmtSettings } | null>(key, null);
  const v = saved?.version === 3 ? saved.settings : null;
  if (!v) return defaults;
  const a = v.anchor;
  return {
    profile: v.profile === true, prior: v.prior === true, bands: v.bands !== false,
    tpo: v.tpo === "letters" || v.tpo === "blocks" ? v.tpo : "off",
    scope: Object.hasOwn(scopes, v.scope) ? v.scope : "session",
    vwap: Object.hasOwn(vwapScopes, v.vwap) ? v.vwap : "off",
    method: v.method === "uniform" ? "uniform" : "hlc3",
    width: Number.isInteger(v.width) && v.width >= 1 && v.width <= 64 ? v.width : defaults.width,
    period: Number.isInteger(v.period) && v.period >= 5 && v.period <= 120 ? v.period : defaults.period,
    opacity: Number.isFinite(v.opacity) && v.opacity >= .1 && v.opacity <= .9 ? v.opacity : defaults.opacity,
    color: validColor(v.color) ? v.color : defaults.color,
    tpoColor: validColor(v.tpoColor) ? v.tpoColor : defaults.tpoColor,
    vwapColor: validColor(v.vwapColor) ? v.vwapColor : defaults.vwapColor,
    start: validDate(v.start) ? v.start : "", end: validDate(v.end) ? v.end : "",
    anchor: a && Number.isFinite(a.time) && Math.abs(a.time) < 8.64e12 &&
      Number.isFinite(a.price) && Number.isFinite(a.availableAt) && a.availableAt >= a.time ? a : null,
  };
}

export function useAmtSettings(key: string) {
  const [record, setRecord] = useState<{ key: string; settings: AmtSettings }>();
  const settings = key && record?.key === key ? record.settings : defaults;
  useEffect(() => {
    if (key) setRecord(current => current?.key === key ? current : { key, settings: readAmt(key) });
  }, [key]);
  const update = useCallback((changes: Partial<AmtSettings>) => {
    if (!key) return;
    const next = { ...settings, ...changes };
    setRecord({ key, settings: next });
    writeLocal(key, { version: 3, settings: next });
  }, [key, settings]);
  return { settings, update };
}

export type Coordinate = { mode: "exact" | "raw"; source_contract: string; segment_id: number | null } |
  { mode: "adjusted"; adjustment_block_id: number };
type Session = { trading_date: string; status: string; observed_minutes: number; elapsed_expected_minutes: number | null;
  lineage: { source_contract: string; segment_id: number | null; adjustment_block_id: number | null; adjustment_offset: number;
    adjustment_status: string } | null };
export type Envelope = {
  contract: string; display: string; scope: string; start: string; end: string; methodology_version: string;
  request_id: string; source: { series: SeriesIdentity; coordinate: Coordinate | null; files: Record<string, string>;
    admission: string; retrospective_prices: boolean };
  cutoff: { as_of: string; publication_verified: boolean; explicit: boolean };
  coverage: { status: string; observed_minutes: number; sessions: Session[]; contributing_sessions: string[];
    all_declared_sessions_complete: boolean; quality: { interval_count: number; unresolved_roll_ids?: string[] } };
};
export type Row = { low_tick: number; high_tick: number };
export type Value = { poc: Row; val_tick: number; vah_tick: number };
export type Profile = Envelope & { profile: { classification: string; rows: (Row & { volume_units: number })[];
  total_volume: number; value: Value | null; nodes: { hvn: Row[]; lvn: Row[] };
  sensitivity: { method: string; delta_ticks: { poc: number; vah: number; val: number } | null } | null } };
export type Balance = { high_tick: number | null; low_tick: number | null; complete: boolean; developing: boolean;
  observed_minutes: number; elapsed_minutes: number };
export type Tpo = Envelope & { tpo: { classification: string; row_ticks: number; value: Value | null;
  rows: (Row & { count: number })[]; initial_balance: Balance[];
  periods: { index: number; letter?: string; partial: boolean; ranges?: [number, number][] }[] } };
export type VwapPoint = { available_at: number; time: number; break_before: boolean; vwap: number | null;
  upper: number | null; lower: number | null };
export type Vwap = Envelope & { vwap: { classification: string; points: VwapPoint[] } };
export type Context = Envelope & { classification: string; previous: { value: Value | null; status: string };
  context: { value_width_ticks: number | null; previous_value_overlap: number | null; poc_migration_ticks: number | null;
    observed_range: { last_close_location: number | null };
    initial_balance_extension: { above_ticks: number | null; below_ticks: number | null }[] } };

export function matchesCoordinate(bar: Bar, coordinate: Coordinate, symbol: string) {
  if (coordinate.mode === "adjusted") return bar.adjustment_block_id === coordinate.adjustment_block_id;
  if (coordinate.mode === "exact") return (bar.source_contract ?? symbol) === coordinate.source_contract;
  return bar.source_contract === coordinate.source_contract && bar.segment_id === coordinate.segment_id;
}

export function useAmtResult<T extends Envelope>(
  endpoint: string, query: string, data: Snapshot | null, series: SeriesIdentity | undefined, replay: boolean,
) {
  const contract = data?.contract, display = data?.display;
  const release = series?.release_id, build = series?.build_id, artifact = series?.artifact_id;
  const cutoff = replay ? data?.as_of : undefined;
  const key = query && contract && display && release ? JSON.stringify([query, release, build, artifact, cutoff]) : "";
  const [record, setRecord] = useState<{ key: string; result?: T; error?: string }>();
  useEffect(() => {
    if (!key || !release) return;
    const controller = new AbortController();
    api<T>("amt/" + endpoint + "?" + query, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      if (!sameSeries(result.source.series, { release_id: release, build_id: build ?? null, artifact_id: artifact ?? null }) ||
          result.contract !== contract || result.display !== display || result.cutoff.explicit !== replay ||
          (cutoff && Date.parse(cutoff) !== Date.parse(result.cutoff.as_of)))
        throw new Error("Auction response does not match the active source and cutoff");
      setRecord({ key, result });
    }).catch(error => {
      if (!controller.signal.aborted) setRecord({ key, error: error.message });
    });
    return () => controller.abort();
  }, [endpoint, key, query, contract, display, release, build, artifact, cutoff, replay]);
  const current = key && record?.key === key ? record : undefined;
  return { result: current?.result, error: current?.error, loading: Boolean(key && !current) };
}
