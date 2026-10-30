"""Retain provider error facts without credentials or sensitive headers."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

_ALLOWED_HEADERS = frozenset({"content-length", "content-type", "date", "request-id", "retry-after"})
_SENSITIVE_NAME = re.compile(r"(authorization|cookie|token|secret|password|api[-_]?key|credential)", re.I)
_SECRET_VALUE = re.compile(
    r"(?i)(db-[a-z0-9_\-]{8,}|bearer\s+[a-z0-9._\-]{8,}|api[_-]?key\s*[=:]\s*\S+|authorization\s*[=:]\s*\S+)"
)
_DOC_HOSTS = frozenset({"databento.com", "docs.databento.com"})


def _redact(value: str) -> str:
    return _SECRET_VALUE.sub("[REDACTED]", value)[:500]


def _safe_docs(url: str) -> str | None:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in _DOC_HOSTS or parsed.username
            or parsed.password):
        return None
    return f"https://{parsed.hostname}{parsed.path}"


def _header_items(headers):
    try:
        return list(headers.items())
    except Exception:
        return []


def _detail(json_body):
    if not isinstance(json_body, dict):
        return {}
    detail = json_body.get("detail")
    kept = {}
    if isinstance(detail, str):
        kept["message"] = _redact(detail)
        return kept
    if not isinstance(detail, dict):
        return {}
    for key in ("case", "message"):
        value = detail.get(key)
        if isinstance(value, str):
            kept[key] = _redact(value)
    docs = detail.get("docs")
    if isinstance(docs, str):
        safe = _safe_docs(docs)
        if safe:
            kept["docs"] = safe
    return kept


def safe_exception_record(exc: BaseException) -> dict:
    """Copy status and correlation fields. Do not infer acceptance from the class name."""
    status = getattr(exc, "http_status", None)
    if type(status) is not int or not 100 <= status <= 599:
        status = None
    request_id = getattr(exc, "request_id", None)
    if request_id is not None:
        request_id = _redact(str(request_id))[:128]
    headers = {}
    for name, value in _header_items(getattr(exc, "headers", None) or {}):
        key = str(name).lower()
        if key in _ALLOWED_HEADERS and _SENSITIVE_NAME.search(key) is None:
            headers[key] = _redact(str(value))[:200]
    if request_id is None and isinstance(headers.get("request-id"), str):
        request_id = headers["request-id"]
    message = getattr(exc, "message", None)
    if not isinstance(message, str):
        message = str(exc)
    body = getattr(exc, "http_body", None)
    body_sha = None
    body_bytes = None
    if body is not None:
        raw = body if isinstance(body, bytes) else str(body).encode()
        body_sha = hashlib.sha256(raw).hexdigest()
        body_bytes = len(raw)
    return {
        "error_type": type(exc).__name__,
        "http_status": status,
        "provider_request_id": request_id,
        "provider_accepted": "UNKNOWN",
        "headers": headers,
        "detail": _detail(getattr(exc, "json_body", None)),
        "http_body_sha256": body_sha,
        "http_body_bytes": body_bytes,
        "message": _redact(message),
    }
