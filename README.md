# Futures research backtester — source only

A standalone source export with one new root commit. This repository contains the core engine, reusable research algorithms, provider adapter source, synthetic example generator, and tests that construct their own inputs.

Historical research workflows, fitted models, empirical results, provider responses, downloaded files, calendars, acquisition records, saved chart fixtures, dashboards tied to those records, and prior Git history are excluded. This is a deliberately reduced source export. The prior private repository and local work are separate from this checkout.

## Setup and verification

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
python -m pytest -q
```

## Generate synthetic examples locally

```sh
python scripts/generate_synthetic_examples.py
python -m backtester validate-data data/synthetic_NQ_1m.csv --symbol NQ --interval 1
```

The generator uses formulas, not observed market records. Its output stays in ignored local folders. Tests use invented values solely to check software behavior.

Never add market records, provider responses, research outputs, credentials, or private evidence to this repository. Provider access requires separately obtained credentials and appropriate data rights.

## Local NQ research terminal

The [terminal setup guide](terminal/README.md) covers the Next.js/FastAPI application, real v2.0.0 dataset binding, causal historical replay, API, and tests. Historical data stays in its existing licensed location; this source export includes no market records.
