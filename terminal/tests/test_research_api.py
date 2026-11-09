"""Synthetic HTTP coverage and fail-closed historical research admission."""
import time

import pytest

from backtester.terminal.research import SPEC

CONFIG = dict(strategy=SPEC['id'], contract='NQZ26', start='2026-01-05',
              end='2026-01-19', eligibility='complete_observed')

def test_historical_gate_before_market_reads(tmp_path,monkeypatch):
    from terminal.research_api import ReleaseWorkspace
    w=ReleaseWorkspace(tmp_path)
    monkeypatch.setenv('NQ_DATA_ROOT',str(tmp_path/'PROTECTED_NOT_TO_BE_READ'))
    try:
        with pytest.raises(ValueError,match='Strict certification NO-GO'):
            w.execute(CONFIG)
    finally:w.close()


def test_api_jobs_artifacts_replay_and_historical_block(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from terminal.api import app
    from terminal import research_api
    w=research_api.ReleaseWorkspace(tmp_path,demo=True)
    monkeypatch.setattr(research_api,'workspace',lambda:w)
    try:
        with TestClient(app) as client:
            assert client.get('/api/research/catalog').json()['mode'].startswith('SYNTHETIC')
            assert client.get('/research/').status_code==200
            assert client.get('/research/app.js').status_code==200
            assert client.get('/research/../server.py').status_code==404
            rejected=client.post('/api/research/experiments',json=CONFIG,headers={'origin':'https://evil.example'})
            assert rejected.status_code==403
            job=client.post('/api/research/experiments',json=CONFIG).json()['job_id']
            for _ in range(200):
                progress=client.get('/api/research/jobs/'+job).json()
                if progress['status'] not in {'queued','running'}:break
                time.sleep(.05)
            assert progress['status']=='completed',progress
            identity=progress['experiment_id']
            artifact=client.get('/api/research/experiments/'+identity).json()
            assert artifact['provenance']['classification']=='SYNTHETIC'
            assert client.get('/api/research/experiments').json()[0]['experiment_id']==identity
            replay=client.get('/api/research/experiments/'+identity,params={'as_of':artifact['events'][0]['signal_at']}).json()
            assert 'metrics' not in replay
            assert client.get('/api/research/experiments/'+identity,params={'as_of':'2026-01-05'}).status_code==422
            assert client.get('/api/research/experiments/'+'0'*64).status_code==404
    finally:w.close()
