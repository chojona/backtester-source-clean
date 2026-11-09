"""Research routes share the terminal's dataset service and scientific gates."""
from functools import lru_cache
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from backtester.market_certification import require_strict_dataset
from backtester.terminal.server import HERE, Workspace
from backtester.terminal.research import replay_view

router = APIRouter()


class ReleaseWorkspace(Workspace):
    def catalog(self):
        if self.demo or self.bundle:
            return super().catalog()
        result = super().catalog()
        root = os.getenv('NQ_DATA_ROOT')
        result['dataset_version'] = 'nq-ohlcv-research-v2.0.0'
        result['dataset_connected'] = bool(root)
        result['blocked'] = ('Strict certification NO-GO: v2.0.0 is retrospectively QC eligible, '
                             'not independently accepted for historical VWAP or signal research. '
                             'Chart browsing remains available; experiment execution is blocked.')
        return result

    def execute(self, config):
        if str(config.get('contract','')).startswith('NQ1!'):
            raise ValueError('BLOCKED: continuous chart series are not executable strategy inputs. Select a certified outright contract.')
        if self.demo or self.bundle:
            return super().execute(config)
        root = os.getenv('NQ_DATA_ROOT')
        if not root:
            raise ValueError('BLOCKED: configure NQ_DATA_ROOT for the sealed v2.0.0 release')
        # Do not instantiate ResearchStore or query any market observations here
        # before certification. A release hash seal is not scientific acceptance.
        manifest = os.getenv('NQ_RESEARCH_CERTIFICATION_MANIFEST')
        for profile in ('VWAP', 'signal'):
            require_strict_dataset(Path(root) / 'research.parquet', manifest,
                                   instrument='NQ', research=profile)
        raise ValueError('BLOCKED: certified release additionally requires a separately bound calendar, '
                         'availability and chronological partition bundle; configure NQ_RESEARCH_BUNDLE')


@lru_cache(maxsize=1)
def workspace():
    bundle_path = os.getenv('NQ_RESEARCH_BUNDLE')
    return ReleaseWorkspace(os.getenv('NQ_EXPERIMENT_STORE', 'results/terminal'),
        demo=os.getenv('NQ_RESEARCH_DEMO') == '1',
        bundle=json.loads(Path(bundle_path).read_text()) if bundle_path else None)


@router.get('/api/research/catalog')
def catalog():
    return workspace().catalog()


@router.get('/api/research/experiments')
def history():
    try:
        return workspace().store.history()
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post('/api/research/experiments', status_code=202)
async def submit(request: Request):
    # Next.js proxies the request; enforce browser same-origin and JSON writes.
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Same-origin request required')
    origin = request.headers.get('origin')
    if origin and origin not in {'http://127.0.0.1:3000', 'http://localhost:3000',
                                  'http://127.0.0.1:8000', 'http://localhost:8000'}:
        raise HTTPException(403, 'Loopback origin required')
    if request.headers.get('content-type') != 'application/json':
        raise HTTPException(415, 'JSON required')
    raw = await request.body()
    if len(raw) > 4096:
        raise HTTPException(413, 'Configuration too large')
    try:
        config = json.loads(raw)
        if not isinstance(config, dict):
            raise ValueError('Configuration object required')
        return {'job_id': workspace().submit(config)}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get('/api/research/jobs/{identity}')
def job(identity: str):
    w = workspace()
    with w.lock:
        if identity not in w.jobs:
            raise HTTPException(404, 'Unknown experiment job')
        return dict(w.jobs[identity])


@router.get('/api/research/experiments/{identity}')
def experiment(identity: str, as_of: str | None = None):
    try:
        return replay_view(workspace().store.get(identity), as_of)
    except FileNotFoundError as error:
        raise HTTPException(404, 'Unknown experiment') from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get('/research/{asset:path}')
def assets(asset: str):
    paths = {'': (HERE / 'index.html', 'text/html'),
             'app.js': (HERE / 'app.js', 'text/javascript'),
             'charts.js': (HERE.parent / 'vendor/lightweight-charts-5.1.0.js', 'text/javascript')}
    if asset not in paths:
        raise HTTPException(404, 'Unknown research asset')
    path, media_type = paths[asset]
    return FileResponse(path, media_type=media_type, headers={'Cache-Control': 'no-store'})
