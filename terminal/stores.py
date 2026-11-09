"""Shared dependencies for the terminal's verified read-only data stores."""
import os
from functools import lru_cache

from fastapi import HTTPException

from .data import ResearchStore

CONTRACT_PATTERN = r'^NQ(?:[HMUZ][0-9]{1,2}|1! (?:Raw|Adjusted))$'


@lru_cache(maxsize=1)
def store():
    root = os.environ.get('NQ_DATA_ROOT')
    if not root:
        raise HTTPException(503, 'Set NQ_DATA_ROOT to the sealed v2.0.0 build directory; no sample data is substituted.')
    try:
        return ResearchStore(root)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, f'Dataset unavailable or invalid: {exc}') from exc


def chart_store(db, contract):
    if contract not in ('NQ1! Raw', 'NQ1! Adjusted'):
        return db
    root = os.getenv('NQ_CONTINUOUS_ROOT')
    if not root:
        raise HTTPException(503, 'Build continuous artifacts and configure NQ_CONTINUOUS_ROOT')
    try:
        return continuous_store(root, db)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, f'Continuous dataset unavailable: {exc}') from exc


@lru_cache(maxsize=1)
def continuous_store(root, db):
    from .continuous_data import ContinuousStore
    return ContinuousStore(root, db)
