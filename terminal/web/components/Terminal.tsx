"use client";
import { useEffect, useState, useRef, type CSSProperties } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  BarChart3,
  ChevronDown,
  Database,
  Focus,
  Layers3,
  LoaderCircle,
  Pause,
  Play,
  Radio,
  RotateCcw,
  Settings2,
  ShieldCheck,
  SkipForward,
  Terminal as TerminalIcon,
  X,
} from "lucide-react";
import MarketChart from "./MarketChart";
import IndicatorManager from "./IndicatorManager";
import {
  defaultWorkspace,
  defaultIndicators,
  readWorkspace,
  writeWorkspace,
  Indicators,
} from "@/lib/workspace";
import Analytics from "./Analytics";
import Explorer from "./Explorer";
import {
  api,
  Contract,
  Session,
  Snapshot,
  Provenance,
  Frame,
  fmt,
  clock,
} from "@/lib/types";
const frames: Frame[] = ["1m", "5m", "15m", "30m", "1h", "daily"];
export default function Terminal() {
  const [historySessions,setHistorySessions]=useState(20);
  const wideHistory=useRef<number|null>(null);
  const [rangeNotice,setRangeNotice]=useState("");
  const [contracts, setContracts] = useState<Contract[]>([]),
    [sessions, setSessions] = useState<Session[]>([]);
  const [contract, setContract] = useState(""),
    [session, setSession] = useState(""),
    [frame, setFrame] = useState<Frame>("1m");
  const [snapshot, setData] = useState<{ data: Snapshot; replay: boolean } | null>(null),
    [provenance, setProvenance] = useState<Provenance | null>(null);
  const [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [retry, setRetry] = useState(0);
  const [cursor, setCursor] = useState<number | null>(null),
    [playing, setPlaying] = useState(false),
    [speed, setSpeed] = useState(1);
  const [ready, setReady] = useState(false),
    [display, setDisplay] = useState<"Globex" | "RTH">("Globex"),
    [settings, setSettings] = useState<Indicators>(defaultIndicators),
    [layout, setLayout] = useState(defaultWorkspace),
    [jump, setJump] = useState(""),
    [storageWarning, setStorageWarning] = useState("");
  const chartPanel = useRef<HTMLDivElement>(null);
  const jumpRequest = useRef<AbortController | null>(null);
  const vwap = settings.vwap.visible,
    levels = settings.levels.visible,
    opening = settings.opening.visible;
  const setVwap = (visible: boolean) =>
    setSettings((s) => ({ ...s, vwap: { ...s.vwap, visible } }));
  const setLevels = (visible: boolean) =>
    setSettings((s) => ({ ...s, levels: { ...s.levels, visible } }));
  const setOpening = (visible: boolean) =>
    setSettings((s) => ({ ...s, opening: { ...s.opening, visible } }));
  const [offset, setOffset] = useState(0),
    [details, setDetails] = useState(false);
  useEffect(() => {
    const state = readWorkspace();
    setHistorySessions(state.historySessions);
    setContract(typeof state.contract === "string" ? state.contract : "");
    setSession(typeof state.session === "string" ? state.session : "");
    setFrame(
      frames.includes(state.frame as Frame) ? (state.frame as Frame) : "1m",
    );
    setDisplay(state.display === "RTH" ? "RTH" : "Globex");
    setSettings({ ...defaultIndicators, ...state.indicators });
    setLayout({
      ...defaultWorkspace,
      ...state,
      width: Math.max(240, Math.min(600, state.width || 290)),
      height: Math.max(260, Math.min(1000, state.height || 480)),
      bottom: Math.max(180, Math.min(900, state.bottom || 300)),
    });
    setReady(true);
  }, []);
  useEffect(() => {
    if (
      ready &&
      !writeWorkspace({
        ...layout,
        contract,
        session,
        frame,
        display,
        indicators: settings,
        historySessions,
      })
    )
      setStorageWarning(
        "Local storage unavailable; settings last for this visit.",
      );
  }, [ready, layout, contract, session, frame, display, settings, historySessions]);
  useEffect(() => {
    if (!ready) return;
    const ac = new AbortController();
    setLoading(true);
    setError("");
    Promise.all([
      api<Contract[]>("contracts", ac.signal),
      api<Provenance>("provenance", ac.signal),
    ])
      .then(([c, p]) => {
        if (ac.signal.aborted) return;
        setContracts(c);
        setProvenance(p);
        setContract((old) => c.some(row => row.contract === old) ? old : c[0]?.contract || "");
        if (!c.length) {
          setError("The sealed release contains no eligible contracts.");
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!ac.signal.aborted) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => ac.abort();
  }, [retry, ready]);
  useEffect(() => {
    if (!ready || !contract) return;
    const ac = new AbortController();
    setLoading(true);
    setError("");
    setSessions([]);
    api<Session[]>(`sessions?contract=${encodeURIComponent(contract)}&limit=${contract.startsWith("NQ1!") ? 5000 : 2000}`, ac.signal)
      .then((s) => {
        if (ac.signal.aborted) return;
        setSessions(s);
        setSession((old) =>
          s.some((row) => row.trading_date === old)
            ? old
            : s[0]?.trading_date || "",
        );
        if (!s.length) {
          setError("No eligible sessions for this contract.");
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!ac.signal.aborted) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => ac.abort();
  }, [contract, retry, ready]);
  const needsIntradayWindow=contract.startsWith("NQ1!") && frame!=="daily" && cursor===null && historySessions>120;
  useEffect(()=>{
    if(!needsIntradayWindow)return;
    wideHistory.current=historySessions;
    setHistorySessions(20);
    setRangeNotice("Intraday · 20 sessions at startup. Pan for earlier history; D restores full history.");
  },[needsIntradayWindow,historySessions]);
  const changeFrame=(next:Frame)=>{
    if(next==='daily' && contract.startsWith('NQ1!') && wideHistory.current!==null){
      setHistorySessions(wideHistory.current);wideHistory.current=null;setRangeNotice('');
    }
    setFrame(next);setOffset(0);
  };
  useEffect(() => {
    if (
      !ready ||
      !contract ||
      !session ||
      !sessions.some(
        (s) => s.trading_date === session && s.contract === contract,
      )
    )
      return;
    const ac = new AbortController();
    setLoading(true);
    setError("");
    const q = new URLSearchParams({
      contract,
      session,
      timeframe: frame,
      offset: String(offset),
      display,
      opening_minutes: String(settings.openingMinutes),
      deviations: String(settings.deviations),
    });
    if (cursor !== null) q.set("cursor", String(cursor));
    api<Snapshot>(`snapshot?${q}`, ac.signal)
      .then((d) => {
        if (ac.signal.aborted) return;
        if (
          cursor !== null &&
          d.explorer.total > 0 &&
          offset !==
            Math.floor((d.explorer.total - 1) / d.explorer.limit) *
              d.explorer.limit
        ) {
          setOffset(
            Math.floor((d.explorer.total - 1) / d.explorer.limit) *
              d.explorer.limit,
          );
        }
        setData({ data: d, replay: cursor !== null });
        setLoading(false);
      })
      .catch((e) => {
        if (!ac.signal.aborted) {
          setError(e.message);
          setPlaying(false);
          setLoading(false);
          setData(null);
        }
      });
    return () => ac.abort();
  }, [
    contract,
    session,
    frame,
    cursor,
    offset,
    retry,
    ready,
    sessions,
    display,
    settings.openingMinutes,
    settings.deviations,
  ]);
  const selected = snapshot?.data;
  const data = selected && selected.contract === contract && selected.session === session &&
    selected.timeframe === frame && selected.display === display && snapshot.replay === (cursor !== null) &&
    (cursor === null || selected.cursor <= cursor) ? selected : null;
  const chartSeries = contract.startsWith("NQ1!") ? provenance?.continuous?.chart_series : provenance?.chart_series;
  useEffect(() => {
    if (!playing || loading || !data || cursor === null) return;
    if (data.cursor >= data.total_minutes) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(
      () => setCursor((c) => Math.min((c ?? 0) + 1, data.total_minutes)),
      1000 / speed,
    );
    return () => clearTimeout(t);
  }, [playing, loading, data, cursor, speed]);
  const reset = () => {
    jumpRequest.current?.abort();
    setPlaying(false);
    setCursor(null);
    setOffset(0);
    setData(null);
  };
  const changeSession = (s: string) => {
    reset();
    setSession(s);
  };
  const enterReplay = () => {
    setPlaying(false);
    setCursor(1);
    setOffset(0);
    setData(null);
  };
  const fullscreen = () => {
    const next = !layout.fullscreen;
    setLayout(l => ({ ...l, fullscreen: next }));
    if (next) void chartPanel.current?.requestFullscreen?.().catch(() => {});
    else if (document.fullscreenElement) void document.exitFullscreen();
  };
  useEffect(() => {
    const onChange = () => {
      if (!document.fullscreenElement) setLayout(l => ({ ...l, fullscreen: false }));
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);
  const stepBar = () => {
    if (loading || !data || cursor === null) return;
    setPlaying(false);
    setCursor(
      Math.min(
        cursor +
          { "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, daily: 1440 }[
            frame
          ],
        data.total_minutes,
      ),
    );
  };
  const jumpToTime = async () => {
    if (cursor === null || !jump) return;
    setPlaying(false);
    jumpRequest.current?.abort();
    const controller = new AbortController();
    jumpRequest.current = controller;
    try {
      const d = await api<{ cursor: number }>(
        `replay-time?${new URLSearchParams({ contract, session, time: jump })}`,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setCursor(d.cursor);
      setOffset(0);
    } catch (e) {
      if (controller.signal.aborted) return;
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      if (
        /INPUT|SELECT|TEXTAREA/.test((e.target as HTMLElement).tagName) ||
        e.ctrlKey ||
        e.metaKey ||
        e.altKey
      )
        return;
      if (e.code === "Space" && cursor !== null) {
        e.preventDefault();
        setPlaying((v) => !v);
      } else if (e.key === "ArrowRight" && cursor !== null) {
        e.preventDefault();
        stepBar();
      } else if (e.key === "Escape" && layout.fullscreen && !document.fullscreenElement) {
        setLayout(l => ({ ...l, fullscreen: false }));
      } else if (e.key.toLowerCase() === "f") {
        e.preventDefault();
        fullscreen();
      }
    };
    document.addEventListener("keydown", fn);
    return () => document.removeEventListener("keydown", fn);
  });
  const resize =
    (axis: "width" | "height" | "bottom") =>
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      const el = e.currentTarget,
        start = axis === "width" ? e.clientX : e.clientY,
        base = layout[axis];
      el.setPointerCapture(e.pointerId);
      el.onpointermove = (event) => {
        const delta =
          (axis === "width" ? event.clientX : event.clientY) - start;
        setLayout((l) => ({
          ...l,
          [axis]: Math.max(
            axis === "width" ? 240 : 260,
            Math.min(
              axis === "width" ? 600 : 1000,
              base + (axis === "width" ? -delta : delta),
            ),
          ),
        }));
      };
      el.onpointerup = () => {
        el.onpointermove = null;
      };
      el.onpointercancel = () => {
        el.onpointermove = null;
      };
    };
  const index = sessions.findIndex((s) => s.trading_date === session);
  const current = sessions[index];
  return (
    <main
      className="terminal"
      style={
        {
          "--sidebar-width": layout.width + "px",
          "--chart-height": layout.height + "px",
        } as CSSProperties
      }
    >
      <nav className="rail" aria-label="Terminal navigation">
        <div className="brand-mark">
          <Activity size={24} />
        </div>
        <button
          className="selected"
          aria-label="Research chart"
          title="Research chart"
        >
          <BarChart3 size={20} />
        </button>
        <button
          onClick={() =>
            document
              .querySelector(".workspace")
              ?.scrollIntoView({ behavior: "smooth" })
          }
          aria-label="Data explorer"
          title="Data explorer"
        >
          <Database size={19} />
        </button>
        <button
          onClick={() => setDetails(true)}
          aria-label="Dataset provenance"
          title="Dataset provenance"
        >
          <ShieldCheck size={20} />
        </button>
        <div className="rail-bottom">
          <span>v0.3</span>
          <button
            onClick={() => setDetails(true)}
            aria-label="Data configuration"
            title="Data configuration"
          >
            <Settings2 size={19} />
          </button>
          <div className="avatar">JC</div>
        </div>
      </nav>
      <div className="terminal-body">
        <header className="topbar">
          <div className="wordmark">
            NQ<span> / </span>QUANT <em>RESEARCH TERMINAL</em>
          </div>
          <div className="top-status">
            <span className="status-dot" />
            LOCAL DATA <i /> <span>HISTORICAL</span>
            <span className="version">v0.3.0</span>
          </div>
        </header>
        <div className="breadcrumb">
          <span>Research workspace</span>
          <span>/</span>
          <b>Market overview</b>
          <div>
            <ShieldCheck size={12} />
            Read-only research environment
          </div>
        </div>
        <div className="page-heading">
          <div>
            <h1>
              Market overview <span>NQ</span>
            </h1>
            <p>
              Explore the session. Observe the structure. Replay the market.
            </p>
          </div>
          <button className="outline-button" onClick={() => setDetails(true)}>
            <Database size={14} />
            Dataset & provenance
            <ChevronDown size={12} />
          </button>
        </div>
        <div
          className={
            "market-layout " + (!layout.analytics ? "analytics-collapsed" : "")
          }
        >
          <section className="market-main">
            <div className={layout.fullscreen ? "chart-panel workspace-fullscreen" : "chart-panel"} ref={chartPanel}>
              <div className="chart-toolbar">
                <div className="instrument">
                  <div className="instrument-icon">NQ</div>
                  <div>
                    <b>E-mini Nasdaq-100</b>
                    <span>CME · Futures</span>
                  </div>
                </div>
                <div className="selector-group">
                  <label className="select-wrap">
                    <span>CONTRACT</span>
                    <select
                      aria-label="Contract"
                      value={contract}
                      onChange={(e) => {
                        reset();
                        setSession("");
                        setContract(e.target.value);
                      }}
                      disabled={!contracts.length}
                    >
                      {!contracts.length && <option>Loading…</option>}
                      {contracts.map((c) => (
                        <option key={c.contract} value={c.contract}>{c.label || c.contract}</option>
                      ))}
                    </select>
                  </label>
                  <i />
                  <div className="date-control">
                    <button
                      aria-label="Previous eligible session"
                      disabled={index < 0 || index >= sessions.length - 1}
                      onClick={() =>
                        changeSession(sessions[index + 1].trading_date)
                      }
                    >
                      <ArrowLeft size={13} />
                    </button>
                    <label className="select-wrap">
                      <span>SESSION DATE · ET</span>
                      <select
                        aria-label="Session date"
                        value={session}
                        disabled={!sessions.length}
                        onChange={(e) => changeSession(e.target.value)}
                      >
                        {!sessions.length && <option>Loading…</option>}
                        {sessions.map((s) => (
                          <option key={s.trading_date}>{s.trading_date}</option>
                        ))}
                      </select>
                    </label>
                    <button
                      aria-label="Next eligible session"
                      disabled={index <= 0}
                      onClick={() =>
                        changeSession(sessions[index - 1].trading_date)
                      }
                    >
                      <ArrowRight size={13} />
                    </button>
                  </div>
                </div>
              </div>
              <div className="chart-options">
                <select
                  aria-label="Session display"
                  value={display}
                  onChange={(e) => {
                    setData(null);
                    setDisplay(e.target.value as "Globex" | "RTH");
                    setOffset(0);
                  }}
                >
                  <option>Globex</option>
                  <option>RTH</option>
                </select>
                <div className="timeframes" aria-label="Chart timeframe">
                  {frames.map((f) => (
                    <button
                      aria-pressed={frame === f}
                      className={frame === f ? "active" : ""}
                      key={f}
                      onClick={() => {
                        changeFrame(f);
                      }}
                    >
                      {f === "daily" ? "D" : f}
                    </button>
                  ))}
                </div>
                <div className="indicator-toggles">
                  <button
                    className={vwap ? "on" : ""}
                    aria-pressed={vwap}
                    onClick={() => setVwap(!vwap)}
                  >
                    <span className="dot gold" />
                    VWAP
                  </button>
                  <button
                    className={levels ? "on" : ""}
                    aria-pressed={levels}
                    onClick={() => setLevels(!levels)}
                  >
                    <Layers3 size={12} />
                    Prev H/L
                  </button>
                  <button
                    className={opening ? "on" : ""}
                    aria-pressed={opening}
                    onClick={() => setOpening(!opening)}
                  >
                    <span className="dot blue" />
                    OR {settings.openingMinutes}m
                  </button>
                </div>
                <button
                  title="Reload current view"
                  aria-label="Reload current view"
                  onClick={() => setRetry((v) => v + 1)}
                >
                  <Focus size={15} />
                </button>
              </div>
              {contract.startsWith("NQ1!") && <div className="workspace-actions">
                <label>Continuous history <select aria-label="Continuous history" value={historySessions} disabled={cursor !== null} onChange={e=>{const n=Number(e.target.value);wideHistory.current=null;setRangeNotice("");setHistorySessions(n);if(n===5000)setFrame("daily");setOffset(0);}}>
                  <option value={1}>Selected session</option><option value={20}>20 sessions</option><option value={120}>120 sessions</option><option value={5000}>Full history · daily</option>
                </select></label>
                <span role="status">{rangeNotice || (contract === "NQ1! Adjusted" ? "Retrospective adjustment blocks · no replay or strategy execution" : "Observed raw prices · roll jumps excluded from returns")}</span>
              </div>}
              <div className="workspace-actions">
                <button aria-label="Chart fullscreen" aria-pressed={layout.fullscreen} onClick={fullscreen}>
                  ⛶ Fullscreen
                </button>
                <button
                  aria-expanded={layout.analytics}
                  onClick={() =>
                    setLayout((l) => ({ ...l, analytics: !l.analytics }))
                  }
                >
                  Analytics
                </button>
                <button
                  aria-expanded={layout.explorer}
                  onClick={() =>
                    setLayout((l) => ({ ...l, explorer: !l.explorer }))
                  }
                >
                  Workspace
                </button>
                <details className="shortcuts">
                  <summary>Shortcuts</summary>
                  <span>
                    Space: play/pause · →: bar · F: fullscreen · Esc: cancel ·
                    Delete: drawing
                  </span>
                </details>
                <span>{storageWarning}</span>
              </div>
              <div className="chart-stage">
                <MarketChart
                  data={data}
                  vwap={vwap}
                  levels={levels}
                  opening={opening}
                  settings={settings}
                  replay={cursor !== null}
                  datasetHash={provenance?.hashes["research.parquet"]}
                  chartSeries={chartSeries}
                  historySessions={contract.startsWith("NQ1!") ? (needsIntradayWindow ? 20 : historySessions) : 20}
                  allowHistory={data?.opening_minutes === settings.openingMinutes && data?.deviations === settings.deviations}
                />
                {loading && (
                  <div
                    className={`chart-message ${data ? "loading-toast" : ""}`}
                    role="status"
                  >
                    <LoaderCircle className="spin" size={20} />
                    <span>
                      {provenance
                        ? "Reading eligible observations…"
                        : "Verifying local dataset…"}
                    </span>
                  </div>
                )}
                {error && (
                  <div className="chart-message error-message" role="alert">
                    <Database size={26} />
                    <h3>Dataset unavailable</h3>
                    <p>{error}</p>
                    <button
                      className="outline-button"
                      onClick={() => setRetry((v) => v + 1)}
                    >
                      Retry connection
                    </button>
                  </div>
                )}
              </div>
              <div className="replay-bar">
                <div className="replay-label">
                  <Radio size={14} />
                  <b>
                    {cursor === null ? "Historical view" : "Session replay"}
                  </b>
                  <span className={cursor === null ? "" : "replay-tag"}>
                    {cursor === null ? "END OF SESSION" : "CAUSAL"}
                  </span>
                </div>
                <div className="replay-controls">
                  {cursor === null ? (
                    <button
                      className="replay-start"
                      disabled={!data || loading || contract === "NQ1! Adjusted"}
                      title={contract === "NQ1! Adjusted" ? "Retrospective adjusted prices cannot be replayed" : "Replay observed raw bars"}
                      onClick={enterReplay}
                    >
                      <Play size={13} />
                      Start replay
                    </button>
                  ) : (
                    <>
                      <button
                        aria-label="Restart replay"
                        onClick={enterReplay}
                        disabled={loading}
                      >
                        <RotateCcw size={13} />
                      </button>
                      <button
                        className="play-button"
                        aria-label={playing ? "Pause replay" : "Play replay"}
                        disabled={
                          loading || !data || data.cursor >= data.total_minutes
                        }
                        onClick={() => setPlaying((p) => !p)}
                      >
                        {playing ? <Pause size={14} /> : <Play size={14} />}
                      </button>
                      <button
                        aria-label="Step forward one minute"
                        disabled={
                          loading || !data || data.cursor >= data.total_minutes
                        }
                        onClick={() => {
                          setPlaying(false);
                          setCursor((c) =>
                            Math.min((c ?? 0) + 1, data?.total_minutes ?? 0),
                          );
                        }}
                      >
                        <SkipForward size={14} />
                      </button>
                      <button
                        aria-label="Step forward one bar"
                        disabled={
                          loading || !data || data.cursor >= data.total_minutes
                        }
                        onClick={stepBar}
                      >
                        Bar →
                      </button>
                      <input
                        type="time"
                        aria-label="Jump to session time"
                        value={jump}
                        onChange={(e) => setJump(e.target.value)}
                      />
                      <button disabled={loading || !jump} onClick={jumpToTime}>
                        Jump
                      </button>
                      <select
                        aria-label="Replay speed"
                        value={speed}
                        onChange={(e) => setSpeed(Number(e.target.value))}
                      >
                        {[1, 2, 5, 10].map((n) => (
                          <option key={n} value={n}>
                            {n}×
                          </option>
                        ))}
                      </select>
                      <button
                        className="exit-replay"
                        onClick={() => {
                          setPlaying(false);
                          setCursor(null);
                          setOffset(0);
                        }}
                      >
                        Exit
                      </button>
                    </>
                  )}
                </div>
                <div className="replay-progress">
                  <div>
                    <i
                      style={{
                        width: `${data ? (data.cursor / data.total_minutes) * 100 : 0}%`,
                      }}
                    />
                  </div>
                  <span data-testid="replay-cursor">
                    {data ? `${data.cursor} / ${data.total_minutes} min` : "—"}
                  </span>
                </div>
                <div className="asof">
                  <b>
                    {data ? clock(data.as_of) : "—"} <span>ET</span>
                  </b>
                  <span>BAR CLOSE CUTOFF</span>
                </div>
              </div>
            </div>
            <div
              role="separator"
              aria-label="Resize chart"
              aria-orientation="horizontal"
              tabIndex={0}
              className="resize-chart"
              onPointerDown={resize("height")}
              onKeyDown={(e) => {
                if (["ArrowUp", "ArrowDown"].includes(e.key)) {
                  e.preventDefault();
                  setLayout((l) => ({
                    ...l,
                    height: Math.max(
                      260,
                      Math.min(
                        1000,
                        l.height + (e.key === "ArrowDown" ? 20 : -20),
                      ),
                    ),
                  }));
                }
              }}
            />
            <div
              className="bottom-workspace"
              hidden={!layout.explorer}
              style={{ height: layout.bottom }}
              onPointerUp={(e) => {
                const bottom = e.currentTarget.getBoundingClientRect().height;
                setLayout((l) => ({ ...l, bottom }));
              }}
            >
              <Explorer data={data} offset={offset} setOffset={setOffset} replay={cursor !== null} />
            </div>
            <div
              role="separator"
              aria-label="Resize workspace"
              aria-orientation="horizontal"
              tabIndex={0}
              className="resize-chart"
              onPointerDown={resize("bottom")}
              onKeyDown={(e) => {
                if (["ArrowUp", "ArrowDown"].includes(e.key)) {
                  e.preventDefault();
                  setLayout((l) => ({
                    ...l,
                    bottom: Math.max(
                      180,
                      Math.min(
                        900,
                        l.bottom + (e.key === "ArrowDown" ? 20 : -20),
                      ),
                    ),
                  }));
                }
              }}
            />
          </section>
          <div
            role="separator"
            aria-label="Resize analytics"
            aria-orientation="vertical"
            tabIndex={0}
            className="resize-analytics"
            onPointerDown={resize("width")}
            onKeyDown={(e) => {
              if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
                e.preventDefault();
                setLayout((l) => ({
                  ...l,
                  width: Math.max(
                    240,
                    Math.min(600, l.width + (e.key === "ArrowLeft" ? 20 : -20)),
                  ),
                }));
              }
            }}
          />
          <div className="analytics-container" hidden={!layout.analytics}>
            <IndicatorManager value={settings} onChange={setSettings} />
            <Analytics data={data} provenance={provenance} />
          </div>
        </div>
        <footer className="statusbar">
          <span>
            <i className="status-dot" />
            {provenance ? "Dataset verified" : "Dataset disconnected"}
            <i>·</i>
            {provenance?.version || "NQ OHLCV research v2.0.0"}
          </span>
          <span>
            {current?.minutes
              ? `${fmt(current.minutes, 0)} observed session minutes`
              : "No session selected"}
            <i>·</i>America/New_York <i>·</i>
            <TerminalIcon size={11} /> LOCAL ONLY
          </span>
        </footer>
      </div>
      {details && (
        <div className="modal-backdrop" onClick={() => setDetails(false)}>
          <section
            className="provenance-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Dataset provenance"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="panel-title">
              <Database size={17} />
              <h2>Dataset & provenance</h2>
              <button
                autoFocus
                aria-label="Close provenance"
                onClick={() => setDetails(false)}
              >
                <X size={18} />
              </button>
            </div>
            <h3>{provenance?.version || "NQ OHLCV research v2.0.0"}</h3>
            <p>
              {provenance?.availability ||
                "Configure NQ_DATA_ROOT on the local FastAPI server."}
            </p>
            <div className="provenance-counts">
              <div>
                <b>{fmt(provenance?.summary.eligible_bars, 0)}</b>
                <span>eligible bars</span>
              </div>
              <div>
                <b>{fmt(provenance?.summary.eligible_sessions, 0)}</b>
                <span>eligible full sessions</span>
              </div>
            </div>
            <p>
              {provenance?.summary.earliest_eligible_date} —{" "}
              {provenance?.summary.latest_eligible_date}
            </p>
            <h4>Integrity & methodology</h4>
            <ul>
              <li>
                SHA-256 verified release artifacts. No market data is copied
                into source.
              </li>
              <li>
                Retrospective research eligibility; strict certification is
                unchanged.
              </li>
              <li>
                Explicit selected contract; no stitching or back adjustment.
              </li>
              <li>
                Replay advances by observed 1m bar close. Higher timeframes may
                show developing candles.
              </li>
              <li>
                VWAP uses HLC3 and bar volume. Opening range is 09:30–10:00 ET.
              </li>
              <li>No volume profile is estimated in v0.3.</li>
            </ul>
            <h4>Fixed roll policy</h4>
            <p>{provenance?.summary.policy.selection}</p>
            <h4>Verified artifact hashes</h4>
            <div className="hashes">
              {Object.entries(provenance?.hashes ?? {}).map(([name, hash]) => (
                <div key={name}>
                  <b>{name}</b>
                  <code>{hash}</code>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
