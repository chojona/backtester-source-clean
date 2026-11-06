export type Frame = "1m" | "5m" | "15m" | "30m" | "1h" | "daily";
export type Bar = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  source_count: number;
  vwap: number | null;
  or_high: number | null;
  or_low: number | null;
  available_at: number;
  partial: boolean;
};
export type Contract = {
  contract: string;
  first_session: string;
  last_session: string;
  sessions: number;
};
export type Session = {
  trading_date: string;
  contract: string;
  minutes: number;
  prior_candidate_date: string;
  calendar_status: string;
  certified_complete: boolean;
  roll: boolean;
  warmup_14_ready: boolean;
};
export type Snapshot = {
  contract: string;
  session: string;
  timeframe: Frame;
  cursor: number;
  total_minutes: number;
  as_of: string;
  session_start: string;
  session_end: string;
  bars: Bar[];
  stats: Record<string, number | null | boolean>;
  previous: { high: number | null; low: number | null; date: string | null };
  explorer: { rows: Bar[]; total: number; offset: number; limit: number };
  eligibility: {
    eligible_full_session: boolean;
    strict_eligible: boolean;
    calendar_status: string;
    roll: boolean;
    warmup_14_ready: boolean;
  };
};
export type Provenance = {
  version: string;
  verified: boolean;
  hashes: Record<string, string>;
  summary: {
    eligible_bars: number;
    eligible_sessions: number;
    earliest_eligible_date: string;
    latest_eligible_date: string;
    excluded_sessions: number;
    policy: Record<string, string | boolean>;
  };
  availability: string;
};
export async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(`/api/${path}`, { signal, cache: "no-store" });
  if (!r.ok) {
    let detail;
    try {
      detail = (await r.json()).detail;
    } catch {
      detail = `API returned ${r.status}`;
    }
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  return r.json();
}
export const fmt = (v: unknown, d = 2) =>
  typeof v === "number"
    ? v.toLocaleString("en-US", {
        minimumFractionDigits: d,
        maximumFractionDigits: d,
      })
    : "—";
export const clock = (v: string | number) =>
  new Date(typeof v === "number" ? v * 1000 : v).toLocaleTimeString("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
