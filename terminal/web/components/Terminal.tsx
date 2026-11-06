"use client";
import { useEffect, useState } from "react";
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
  const [contracts, setContracts] = useState<Contract[]>([]),
    [sessions, setSessions] = useState<Session[]>([]);
  const [contract, setContract] = useState(""),
    [session, setSession] = useState(""),
    [frame, setFrame] = useState<Frame>("1m");
  const [data, setData] = useState<Snapshot | null>(null),
    [provenance, setProvenance] = useState<Provenance | null>(null);
  const [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [retry, setRetry] = useState(0);
  const [cursor, setCursor] = useState<number | null>(null),
    [playing, setPlaying] = useState(false),
    [speed, setSpeed] = useState(1);
  const [vwap, setVwap] = useState(true),
    [levels, setLevels] = useState(true),
    [opening, setOpening] = useState(true),
    [offset, setOffset] = useState(0),
    [details, setDetails] = useState(false);
  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    setError("");
    Promise.all([
      api<Contract[]>("contracts", ac.signal),
      api<Provenance>("provenance", ac.signal),
    ])
      .then(([c, p]) => {
        setContracts(c);
        setProvenance(p);
        setContract((old) => old || c[0]?.contract || "");
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
  }, [retry]);
  useEffect(() => {
    if (!contract) return;
    const ac = new AbortController();
    setLoading(true);
    setError("");
    setSessions([]);
    api<Session[]>(`sessions?contract=${contract}`, ac.signal)
      .then((s) => {
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
  }, [contract, retry]);
  useEffect(() => {
    if (!contract || !session) return;
    const ac = new AbortController();
    setLoading(true);
    setError("");
    const q = new URLSearchParams({
      contract,
      session,
      timeframe: frame,
      offset: String(offset),
    });
    if (cursor !== null) q.set("cursor", String(cursor));
    api<Snapshot>(`snapshot?${q}`, ac.signal)
      .then((d) => {
        setData(d);
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
  }, [contract, session, frame, cursor, offset, retry]);
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
  const index = sessions.findIndex((s) => s.trading_date === session);
  const current = sessions[index];
  return (
    <main className="terminal">
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
          <span>v0.1</span>
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
            <span className="version">v0.1.0</span>
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
        <div className="market-layout">
          <section className="market-main">
            <div className="chart-panel">
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
                        <option key={c.contract}>{c.contract}</option>
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
                <div className="timeframes" aria-label="Chart timeframe">
                  {frames.map((f) => (
                    <button
                      aria-pressed={frame === f}
                      className={frame === f ? "active" : ""}
                      key={f}
                      onClick={() => {
                        setFrame(f);
                        setOffset(0);
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
                    OR 30m
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
              <div className="chart-stage">
                <MarketChart
                  data={data}
                  vwap={vwap}
                  levels={levels}
                  opening={opening}
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
                      disabled={!data || loading}
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
                      <select
                        aria-label="Replay speed"
                        value={speed}
                        onChange={(e) => setSpeed(Number(e.target.value))}
                      >
                        {[1, 2, 4, 8].map((n) => (
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
            <Explorer data={data} offset={offset} setOffset={setOffset} />
          </section>
          <Analytics data={data} provenance={provenance} />
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
              <li>No volume profile is estimated in v0.1.</li>
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
