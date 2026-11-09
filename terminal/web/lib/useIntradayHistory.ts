import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Snapshot } from "./types";

type Continuous = NonNullable<Snapshot["continuous"]>;
type Window = Pick<Snapshot, "bars" | "as_of"> &
  Pick<Continuous, "session_dates" | "gaps" | "rolls">;
type Page = Omit<Window, "as_of"> & {
  as_of: string | null;
  contract: string;
  build_id: string;
  timeframe: Snapshot["timeframe"];
  display: Snapshot["display"];
  at_edge: boolean;
};
export type Direction = "older" | "newer";
type History = {
  scope: string;
  window: Window;
  edges: Record<Direction, boolean>;
  pending?: Direction;
  failed?: Direction;
};

const maxCachedSessions = 140;

function mergeWindow(current: Window, page: Page, direction: Direction): Window {
  const dates = [...new Set([...current.session_dates, ...page.session_dates])].sort();
  const session_dates = direction === "older"
    ? dates.slice(0, maxCachedSessions)
    : dates.slice(-maxCachedSessions);
  const retained = new Set(session_dates);
  const bars = new Map<number, Snapshot["bars"][number]>();
  for (const bar of [...current.bars, ...page.bars]) {
    if (bar.trading_date && retained.has(bar.trading_date) && !bars.has(bar.time))
      bars.set(bar.time, bar);
  }
  const gaps = new Map<string, Continuous["gaps"][number]>();
  for (const gap of [...current.gaps, ...page.gaps]) {
    if (retained.has(gap.trading_date))
      gaps.set(`${gap.trading_date}/${gap.start_utc}/${gap.end_exclusive_utc}`, gap);
  }
  const rolls = new Map<string, Continuous["rolls"][number]>();
  for (const roll of [...current.rolls, ...page.rolls]) {
    if (retained.has(roll.trading_date)) rolls.set(roll.roll_id, roll);
  }
  return {
    bars: [...bars.values()].sort((a, b) => a.time - b.time),
    session_dates,
    gaps: [...gaps.values()],
    rolls: [...rolls.values()].sort((a, b) => a.trading_date.localeCompare(b.trading_date)),
    as_of: direction === "newer" ? page.as_of ?? current.as_of : current.as_of,
  };
}

export function useIntradayHistory(base: Snapshot | null, enabled: boolean) {
  const continuous = base?.continuous;
  const scope = enabled && base && continuous && base.timeframe !== "daily"
    ? JSON.stringify([continuous.build_id, base.contract, base.session, base.timeframe,
        base.display, base.opening_minutes, base.deviations, continuous.history_sessions])
    : null;
  const [history, setHistory] = useState<History | null>(null);
  const activeScope = useRef(scope);
  activeScope.current = scope;
  const request = useRef<{ scope: string; controller: AbortController } | null>(null);
  const active = history?.scope === scope ? history : null;

  useEffect(() => {
    setHistory(previous => previous?.scope === scope ? previous : null);
    return () => {
      if (request.current && request.current.scope === scope) {
        request.current.controller.abort();
        request.current = null;
      }
    };
  }, [scope]);

  async function load(direction: Direction) {
    if (!scope || !base || !continuous || request.current || active?.edges[direction]) return;
    const current = active ?? {
      scope,
      window: {
        bars: base.bars, as_of: base.as_of, session_dates: continuous.session_dates,
        gaps: continuous.gaps, rolls: continuous.rolls,
      },
      edges: { older: false, newer: false },
    };
    const dates = current.window.session_dates;
    const anchor = direction === "older" ? dates[0] : dates.at(-1);
    if (!anchor) return;
    const controller = new AbortController();
    request.current = { scope, controller };
    setHistory({ ...current, pending: direction, failed: undefined });
    const query = new URLSearchParams({
      contract: base.contract, anchor, direction, timeframe: base.timeframe, display: base.display,
      opening_minutes: String(base.opening_minutes), deviations: String(base.deviations),
    });
    try {
      const page = await api<Page>(`continuous/intraday?${query}`, controller.signal);
      if (controller.signal.aborted || activeScope.current !== scope) return;
      if (page.build_id !== continuous.build_id || page.contract !== base.contract ||
          page.timeframe !== base.timeframe || page.display !== base.display ||
          page.session_dates.some(date => direction === "older" ? date >= anchor : date <= anchor) ||
          page.bars.some(bar => bar.retrospective !== continuous.retrospective))
        throw new Error("Intraday history identity mismatch");
      const window = mergeWindow(current.window, page, direction);
      const edges = { ...current.edges, [direction]: page.at_edge };
      if (direction === "older" && window.session_dates.at(-1) !== dates.at(-1)) edges.newer = false;
      if (direction === "newer" && window.session_dates[0] !== dates[0]) edges.older = false;
      setHistory({ scope, window, edges });
    } catch {
      if (!controller.signal.aborted && activeScope.current === scope)
        setHistory({ ...current, pending: undefined, failed: direction });
    } finally {
      if (request.current?.controller === controller) request.current = null;
    }
  }

  const window = active?.window;
  const data = useMemo(() => base && continuous && window ? {
    ...base,
    bars: window.bars,
    as_of: window.as_of,
    continuous: {
      ...continuous,
      session_dates: window.session_dates,
      history_sessions: window.session_dates.length,
      gaps: window.gaps,
      rolls: window.rolls,
    },
  } : base, [base, continuous, window]);

  return { data, load, enabled: !!scope, pending: active?.pending, failed: active?.failed, edges: active?.edges };
}
