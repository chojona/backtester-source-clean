# NQ Quant Research Terminal v0.1

Local Next.js / TypeScript / Tailwind / Lightweight Charts frontend, backed by a read-only FastAPI / DuckDB service. Uses the existing sealed **nq-ohlcv-research-v2.0.0** release. No market data is bundled, fabricated, copied into source, or downloaded. Research and strict certification rules are unchanged.

## Install and launch

Requires Python 3.12+, Node 22+, npm, and the existing licensed dataset.

From the repository root:

```sh
python3.12 -m venv .venv-terminal
.venv-terminal/bin/pip install -r terminal/requirements.txt
cd terminal/web
npm ci
cd ../..
cp terminal/.env.example terminal/.env
# Edit terminal/.env: NQ_DATA_ROOT must point to the existing release's build directory.
.venv-terminal/bin/python -m terminal.launch
```

Open **http://127.0.0.1:3000**. Both servers bind only to loopback; Ctrl-C stops both. Ports 3000 and 8000 must be free. The ignored `terminal/.env` in the development workspace is already configured to the discovered sibling research release; no user-specific path is committed. An exported `NQ_DATA_ROOT` overrides that file.

For production mode:

```sh
cd terminal/web
npm run build
cd ../..
.venv-terminal/bin/python -m terminal.launch --production
```

For separate processes, export `NQ_DATA_ROOT` and run `.venv-terminal/bin/python -m uvicorn terminal.api:app --host 127.0.0.1 --port 8000`, then `cd terminal/web && npm run dev`. `NQ_API_URL` can override the frontend's backend destination when starting/building Next.js. Default is `http://127.0.0.1:8000`.

## Dataset binding

`NQ_DATA_ROOT` must contain `SUCCESS.json`, `summary.json`, `input-bindings.json`, `research.parquet`, `session-eligibility.parquet`, `selected-observations-with-flags.parquet`, and `contract-rolls.parquet` from the sealed release. The service verifies all six consumed artifact hashes against `SUCCESS.json` before serving data. This verifies consistency against the local seal, not independent authenticity or a new certification. The immutable release must remain unchanged while the service runs; restart after any source change. Missing files or a hash mismatch produce an actionable 503, never demo candles.

The expected release has 2,141,265 eligible bars and 1,557 eligible full sessions, 2016-01-21 through 2026-10-06. Every chart query filters `eligible_full_session IS TRUE`, exact `contract`, and matching `selected_contract`. Session manifests must reconcile to observed counts. The full-session release is retrospectively QC eligible and **not strict certified**; original calendar and point-in-time limitations remain in provenance. Eligibility is not proof that a session or bar was historically published at that instant.

DuckDB queries Parquet with date, contract, availability, and eligibility predicates. Only one session (at most 1,395 source minutes in this release) reaches the snapshot calculation. Range requests are limited to 32 dates, all on one explicit contract. No whole dataset is loaded into browser memory. Historical and derived data remain local. No brokerage or trade execution is implemented.

## Use

- Select a contract, then an eligible session date. Arrow buttons navigate eligible dates within that contract.
- Choose 1m / 5m / 15m / 30m / 1h / D. D is the selected session's daily candle. Buckets are anchored at the first observed session minute. Scheduled breaks are left empty, and no bars are filled.
- Pan by dragging, zoom with the wheel or pinch, and hover for OHLC and volume. Toggle VWAP, previous-session H/L, or the opening range.
- **Start replay** resets to the first completed observed 1m bar. Play, pause, restart, or step one minute forward. Speed controls the delay between observations; API latency adds to this delay. Exit returns to the completed historical session.
- Data Explorer paginates the selected timeframe's observed candles; search filters only the current page. Aggregated rows include their source-minute count and developing status. The remaining workspace tabs are explicitly inactive.
- Dataset & provenance shows release counts, roll policy, limitations, and verified hashes.

## Causality and indicator definitions

Replay requests use a server-side observed-minute cursor. An optional timezone-aware `as_of` additionally filters observations to `bar open + 1 minute <= as_of`. Raw bars are filtered **before** aggregation, statistics, VWAP, and opening-range calculations. A single atomic snapshot supplies the chart, sidebar, and explorer. Stale selection requests are aborted. Replay does not fetch future prices, and crosshair state resets when a session changes or becomes unavailable. Session bounds, minute totals, and retrospective eligibility are metadata, not simulated historical knowledge.

VWAP resets at the ordinary session open and uses cumulative `HLC3 × volume / volume`, an OHLCV approximation rather than trade-level VWAP. Aggregated VWAP uses the last known source-minute VWAP. Previous high/low comes only from the manifest's exact prior candidate date on the same selected contract, requiring a complete observed grid with no boundary issue; unavailable context stays null. Prior-session records also respect the cutoff. No context is borrowed across a roll or skipped date.

Opening range is [09:30,10:00) **America/New_York**, honoring DST. It remains absent before 09:30 and developing until 10:00. Developing higher-timeframe candles contain only completed source minutes; their current VWAP and OR values are known at the returned `available_at`, not necessarily at the bucket's displayed open timestamp. Realized volatility is `100 × sqrt(sum(log(C_t/C_(t-1))²))` across consecutive observed one-minute timestamps within the session, unannualized; gaps and cross-session returns are excluded. No volume profile is implemented.

## API

Interactive schema: **http://127.0.0.1:8000/docs**.

| Endpoint | Parameters / behavior |
| --- | --- |
| `GET /api/health` | Dataset verification and readiness |
| `GET /api/contracts` | Contracts with eligible coverage |
| `GET /api/sessions` | Optional `contract`, `start`, `end`; `limit<=2000`, `offset` |
| `GET /api/snapshot` | Required `contract`, `session`; optional `timeframe`, `cursor`, `as_of`, `offset`, `limit<=500` |
| `GET /api/bars` | Required `contract`, inclusive `start`, `end`; at most 31 days apart; optional `timeframe`, `as_of`; separate session arrays |
| `GET /api/statistics` | Same selection and cutoff parameters as snapshot |
| `GET /api/indicators` | Same parameters; points carry decision-time availability |
| `GET /api/provenance` | Release summary, hashes, definitions, and limitations |
| `GET /api/rolls` | Required `contract`; explicit release roll records |

Snapshot `cursor=0` exposes no current-session prices. Omitting cursor shows the full eligible historical session. Invalid contracts, excluded dates, unknown timeframes, invalid ranges, naive `as_of`, and out-of-bounds cursors return 422. Empty range results remain empty. Times in JSON include UTC offsets; chart labels are ET. Each range session and daily aggregate retains the exact requested contract identity.

## Verification

Historical tests require the actual release and explicitly skip without `NQ_DATA_ROOT`:

```sh
# Export the path configured in terminal/.env into this shell.
set -a
. terminal/.env
set +a
.venv-terminal/bin/python -m pytest terminal/tests -q
cd terminal/web
npm run typecheck
npm run build
npx playwright install chromium
# With both servers running:
npm run test:smoke
```

If Chromium already exists, `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/absolute/path/to/chrome-headless-shell npm run test:smoke` uses it without downloading another copy.

Tests compare real source rows to API candles, verify causal prefixes and aggregation across all six timeframes, independently recompute VWAP and OR, check exact contract and eligibility rejection, timestamp availability at close, source hash failure, pagination, bounded requests, error recovery, responsive layout, and browser replay controls. Existing research tests remain separate (`python -m pytest tests`). Browser screenshots and traces are ignored generated outputs under `terminal/web/test-results/`.
