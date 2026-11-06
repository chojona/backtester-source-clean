# Development and verification

Start with [setup](GETTING_STARTED.md) and the [code map](ARCHITECTURE.md). Keep generated artifacts and external datasets outside commits; the [source boundary](../PUBLIC_EXPORT.md) applies to documentation and fixtures as well as application code.

## Core Python checks

From the repository root, with the core environment activated:

```sh
python -m pytest tests -q
python scripts/check_source_boundary.py
git diff --check
```

`pytest.ini` sets `testpaths = tests`, so bare `python -m pytest` does **not** run `terminal/tests`. The core tests construct their own inputs. Optional dependency/provider checks can skip; no live provider test should be assumed to run from this command.

Examples of focused suites:

```sh
python -m pytest tests/test_data_sessions.py tests/test_intraday.py -q
python -m pytest tests/test_volatility.py tests/test_volatility_charts.py -q
python -m pytest tests/test_research_nq_adapter.py tests/test_research_nq_m1r_counterexamples.py -q
python -m pytest tests/test_source_boundary.py -q
```

Install the `charts` extra to exercise Matplotlib export checks and make Node available for the chart-adapter checks. Consult each provider test's explicit dependency and live-opt-in conditions before interpreting a skip as coverage.

## Terminal backend checks

Install `terminal/requirements.txt` into `.venv-terminal`. Historical integration tests require the existing sealed release. Export the configured path into the test process:

```sh
set -a
. terminal/.env
set +a
.venv-terminal/bin/python -m pytest terminal/tests -q
```

The launcher reads `terminal/.env` for its child processes; that does not load the file into an unrelated test shell. Without `NQ_DATA_ROOT`, historical integration fixtures skip explicitly. No fabricated release is substituted.

The backend suite checks source row equivalence, exact contract identity, eligibility/count reconciliation, changed artifact rejection, aggregation, causal prefixes, timestamp availability, indicator math, previous-session context, parameter bounds, pagination, and replay time jumps.

## Frontend checks

```sh
cd terminal/web
npm ci
npm run typecheck
npm run build
```

Use `npm run dev` for development and `npm run start` for an existing production build. The combined launcher is described in the [terminal guide](../terminal/README.md#install-and-launch). `NQ_API_URL` controls the backend rewrite destination; use the intended value when building a production frontend, not only when starting it.

For browser verification, run the frontend and API with the actual release, then:

```sh
cd terminal/web
npx playwright install chromium
npm run test:smoke
```

If a compatible Chromium already exists:

```sh
PLAYWRIGHT_CHROMIUM_EXECUTABLE=/absolute/path/to/chrome-headless-shell \
  npm run test:smoke
```

`TERMINAL_URL` can override the default browser-test base URL, `http://127.0.0.1:3000`. The browser suite includes real-data interaction tests and a pure drawing projection check. It covers selection, replay, Explorer synchronization, drawing operations, local persistence, layout changes, fullscreen, responsive behavior, API error recovery, and unavailable local storage.

Screenshots and failed-test traces are written under ignored `terminal/web/test-results/`. They can contain market data and remain local review artifacts.

## What CI currently runs

[The GitHub Actions workflow](../.github/workflows/source-boundary.yml) checks out full Git history, uses Python 3.12, runs the source-boundary checker, installs `.[test]`, and runs the default offline pytest suite.

It does not install terminal requirements, build Next.js, supply licensed historical data, or run Playwright. Run the applicable terminal checks locally for terminal changes; a green offline CI job alone does not verify the terminal.

## Preparing a change

1. Read any applicable `AGENTS.md` instructions. The frontend also contains Next.js-generated guidance pointing to its installed local documentation.
2. Keep bar timestamp/availability semantics explicit. Test changes to aggregation or indicators on a bounded prefix, not just a completed full session.
3. Preserve exact-contract and eligibility predicates. Do not turn a UI feature into a change to certification or production trust roots.
4. Add meaningful regressions for changed behavior. Existing source-only fixtures belong in tests; historical records and generated outputs do not.
5. Run the relevant Python/frontend/browser checks, then inspect `git diff --check`, `git status --short`, and the staged file list.
6. After committing, rerun `python scripts/check_source_boundary.py` before pushing. It examines every blob in reachable committed history, including older revisions; it does not inspect uncommitted files.

Never force-add ignored datasets, `.env`, screenshots, traces, or build directories. Run/test counts in the [v0.2 report](../terminal/IMPLEMENTATION_V0_2.md) describe that verification run; they are not a promise that every future checkout has an identical dependency environment or test count.
