import { useEffect, useMemo, useRef, useState } from "react";
import { fetchChartWindow, type ChartWindow, type Direction, type SeriesIdentity } from "./chartWindow";
import type { Snapshot } from "./types";

export const maxChartCandles = 30_000;
const maxPages = 32;
type Load = Direction | "initial";
type History = { scope: string; pages: ChartWindow[]; pending?: Load; failed?: Load };

function addPage(pages: ChartWindow[], page: ChartWindow, direction: Direction) {
  const next = direction === "older" ? [page, ...pages] : [...pages, page];
  let count = next.reduce((total, entry) => total + entry.bars.length, 0);
  while (count > maxChartCandles || next.length > maxPages)
    count -= (direction === "older" ? next.pop()! : next.shift()!).bars.length;
  return next;
}

function pageEdge(pages: ChartWindow[], direction: Direction) {
  const page = direction === "older" ? pages[0] : pages.at(-1);
  const cursor = page?.[direction === "older" ? "older_cursor" : "newer_cursor"];
  const day = direction === "older" ? page?.session_dates[0] : page?.session_dates.at(-1);
  return page && cursor && day ? { cursor, day, direction, scope: page.scope } : undefined;
}

export function useChartHistory(base: Snapshot | null, series: SeriesIdentity | undefined, goal: number, startSession: string) {
  const scope = base && series ? JSON.stringify([
    series.release_id, series.build_id, series.artifact_id, base.contract, base.session,
    base.timeframe, base.display, base.opening_minutes, base.deviations, goal, startSession,
  ]) : "";
  const [state, setState] = useState<History | null>(null);
  const cached = useRef<History | null>(null);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const request = useRef<{ scope: string; controller: AbortController } | null>(null);
  const active = scope && state?.scope === scope ? state : null;

  async function load(kind: Load) {
    if (!scope || !base || !series || request.current) return;
    const previous = cached.current?.scope === scope ? cached.current.pages : [];
    const edge = kind === "initial" ? undefined : pageEdge(previous, kind);
    if (kind !== "initial" && !edge) return;
    const pageSize = goal > 20 && base.timeframe === "daily" && series.build_id ? 250 : 20;
    const initialSize = Math.min(goal, pageSize);
    const controller = new AbortController();
    request.current = { scope, controller };
    const publish = (next: Omit<History, "scope">) => {
      if (controller.signal.aborted || currentScope.current !== scope) return;
      cached.current = { ...next, scope };
      setState(cached.current);
    };
    publish({ pages: previous, pending: kind });
    try {
      const page = await fetchChartWindow(base, series, pageSize, initialSize, controller.signal, startSession, edge);
      let pages = kind === "initial" ? [page] : addPage(previous, page, kind);
      if (kind === "initial" && goal > 1) {
        publish({ pages, pending: kind });
        let sessions = page.session_dates.length, count = page.bars.length;
        for (let older = pageEdge(pages, "older"); older && sessions < goal &&
             count + 2500 <= maxChartCandles && pages.length < maxPages; older = pageEdge(pages, "older")) {
          const prior = await fetchChartWindow(base, series, pageSize, initialSize, controller.signal, startSession, older);
          if (controller.signal.aborted || currentScope.current !== scope) return;
          // Keep the chosen session in the startup cache. Panning can evict it later.
          pages = [prior, ...pages];
          sessions += prior.session_dates.length;
          count += prior.bars.length;
        }
      }
      publish({ pages });
    } catch {
      publish({ pages: cached.current?.scope === scope ? cached.current.pages : previous, failed: kind });
    } finally {
      if (request.current?.controller === controller) request.current = null;
    }
  }

  useEffect(() => {
    if (scope && (!cached.current || cached.current.scope !== scope || !cached.current.pages.length))
      void load("initial");
    return () => {
      if (request.current?.scope === scope) {
        request.current.controller.abort();
        request.current = null;
      }
    };
    // A snapshot refresh for explorer pagination keeps the same chart identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  const pages = active?.pages;
  const window = useMemo(() => {
    if (!pages?.length) return null;
    const observations = new Map<number, ChartWindow["bars"][number]>();
    for (const page of pages)
      for (const bar of page.bars)
        if (!observations.has(bar.time)) observations.set(bar.time, bar);
    return {
      bars: [...observations.values()].sort((a, b) => a.time - b.time),
      session_dates: [...new Set(pages.flatMap(page => page.session_dates))].sort(),
      gaps: pages.flatMap(page => page.gaps),
      rolls: pages.flatMap(page => page.rolls),
      gap_count: pages.reduce((n, page) => n + page.gap_count, 0),
      gaps_truncated: pages.some(page => page.gaps_truncated),
      unavailable_sessions: pages.flatMap(page => page.unavailable_sessions),
      session_context: Object.assign({}, ...pages.map(page => page.session_context)) as ChartWindow["session_context"],
    };
  }, [pages]);

  const data = useMemo(() => {
    if (!base || !window) return base;
    const end = window.gaps.reduce((latest, gap) => Math.max(latest, Date.parse(gap.end_exclusive_utc)),
      Math.max((window.bars.at(-1)?.available_at ?? 0) * 1000, Date.parse(base.as_of)));
    return {
      ...base,
      bars: window.bars,
      as_of: new Date(end).toISOString(),
      boundaries: Object.values(window.session_context).flatMap(context => context.boundaries),
      continuous: base.continuous && {
        ...base.continuous,
        session_dates: window.session_dates,
        gaps: window.gaps,
        gap_count: window.gap_count,
        gaps_truncated: window.gaps_truncated,
        rolls: window.rolls,
        history_sessions: window.session_dates.length,
        ineligible_sessions: window.unavailable_sessions,
      },
    };
  }, [base, window]);

  return {
    data, window, load, scope, enabled: Boolean(scope),
    pending: active?.pending, failed: active?.failed,
    edges: pages?.length ? { older: !pageEdge(pages, "older"), newer: !pageEdge(pages, "newer") } : undefined,
  };
}
