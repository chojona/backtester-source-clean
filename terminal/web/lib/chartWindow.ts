import { api, type Bar, type Frame, type Snapshot } from "./types";

export type Direction = "older" | "newer";
type Continuous = NonNullable<Snapshot["continuous"]>;
export type SeriesIdentity = { release_id: string; build_id: string | null; artifact_id: string | null };
export type ChartWindow = {
  contract: string;
  timeframe: Frame;
  display: Snapshot["display"];
  opening_minutes: number;
  deviations: number;
  as_of: string | null;
  series: SeriesIdentity;
  scope: string;
  retrospective: boolean;
  session_dates: string[];
  bars: Bar[];
  gaps: Continuous["gaps"];
  gap_count: number;
  gaps_truncated: boolean;
  rolls: Continuous["rolls"];
  unavailable_sessions: Continuous["ineligible_sessions"];
  session_context: Record<string, Pick<Snapshot, "previous" | "boundaries">>;
  older_cursor: string | null;
  newer_cursor: string | null;
  has_older: boolean;
  has_newer: boolean;
};

export function sameSeries(a: SeriesIdentity, b: SeriesIdentity) {
  return a.release_id === b.release_id && a.build_id === b.build_id && a.artifact_id === b.artifact_id;
}

export async function fetchChartWindow(
  base: Snapshot, expected: SeriesIdentity, pageSize: number, initialSize: number, signal: AbortSignal,
  startSession: string,
  edge?: { cursor: string; direction: Direction; day: string; scope: string },
) {
  const query = new URLSearchParams({
    contract: base.contract, timeframe: base.timeframe, display: base.display,
    opening_minutes: String(base.opening_minutes), deviations: String(base.deviations),
    sessions: String(pageSize),
  });
  if (edge) query.set("cursor", edge.cursor);
  else {
    query.set("session", startSession);
    query.set("start_sessions", String(initialSize));
  }
  const page = await api<ChartWindow>("chart/window?" + query, signal);
  const dates = new Set(page.session_dates);
  if (!sameSeries(page.series, expected) || page.contract !== base.contract ||
      page.timeframe !== base.timeframe || page.display !== base.display ||
      page.opening_minutes !== base.opening_minutes || page.deviations !== base.deviations ||
      page.as_of !== null || page.retrospective !== (base.contract === "NQ1! Adjusted") ||
      page.has_older !== Boolean(page.older_cursor) || page.has_newer !== Boolean(page.newer_cursor) ||
      page.bars.length > 2500 || page.session_dates.length > pageSize ||
      page.bars.some(bar => !bar.trading_date || !dates.has(bar.trading_date) ||
        Boolean(bar.retrospective) !== page.retrospective ||
        (!expected.build_id && bar.source_contract !== base.contract)) ||
      (edge && (page.scope !== edge.scope || !dates.size || page.session_dates.some(
        day => edge.direction === "older" ? day >= edge.day : day <= edge.day,
      ))))
    throw new Error("Chart window identity mismatch");
  return page;
}
