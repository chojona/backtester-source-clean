"""Keep terminal source allowances narrow and research artifacts excluded."""
import pytest

from scripts.check_source_boundary import source_path_allowed


@pytest.mark.parametrize('path', [
    'terminal/web/app/page.tsx',
    'terminal/web/lib/types.ts',
    'terminal/web/app/globals.css',
    'terminal/web/postcss.config.mjs',
    'terminal/web/package.json',
    'terminal/web/package-lock.json',
    'terminal/web/tsconfig.json',
    'terminal/.env.example',
    'terminal/api.py',
])
def test_terminal_source_allowed(path):
    assert source_path_allowed(path)


@pytest.mark.parametrize('path', [
    'terminal/.env',
    'terminal/web/.env.local',
    'terminal/web/market.json',
    'terminal/web/fixtures/bars.json',
    'terminal/data.parquet',
    'terminal/web/bars.csv',
    'terminal/web/preview.png',
    'other/app.tsx',
    'other/package.json',
    'results/app.tsx',
    'data/source.py',
    'frontend/app.tsx',
    'config/capture-manifest.json',
    'backtester/nq_private.py',
    'tests/test_nq_private.py',
])
def test_historical_and_private_paths_stay_excluded(path):
    assert not source_path_allowed(path)
