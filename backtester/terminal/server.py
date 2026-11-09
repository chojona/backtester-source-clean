"""Loopback HTTP API, immutable content-addressed artifacts, trusted local inputs.

Run: python -m backtester.terminal.server --demo --store /tmp/nq-terminal
Historical bundles are local administrator configuration, never browser paths.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import tempfile
from threading import Lock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from backtester.data import Bar
from backtester.market_certification import require_strict_dataset
from backtester.research_nq.adapter import ReadOnlyExploratoryAdapter
from backtester.research_nq.binding import decode_dataset_bars
from backtester.research_nq.manifest import load_manifest
from backtester.research_nq.testing_support import bound_manifest, traded
from backtester.sessions import local_at
from .research import SPEC, canonical, digest, parse, replay_view, run

HERE = Path(__file__).parent


def demo_inputs():
    """Constructed formulas only, never used as fallback for absent market data."""
    bars, partitions = [], {}
    day = date(2026, 1, 5)
    for n in range(12):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        key = day.isoformat()
        partitions[key] = "development" if n < 6 else "validation" if n < 11 else "final_holdout"
        t, stop = local_at(day - timedelta(days=1), "18:00"), local_at(day, "12:17")
        i = 0
        while t < stop:
            price = 21000 + 6 * math.sin(i / 9 + n) + 2 * math.sin(i / 31)
            bars.append(traded(t, price))
            t += timedelta(minutes=1)
            i += 1
        day += timedelta(days=1)
    manifest, data, calendar = bound_manifest(bars, time_range={
        "start_utc": bars[0].timestamp.isoformat().replace("+00:00", "Z"),
        "end_utc": bars[-1].end.isoformat().replace("+00:00", "Z")})
    return ReadOnlyExploratoryAdapter(manifest, bars, dataset_bytes=data, calendar_bytes=calendar), partitions


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, result):
        identity = result["experiment_id"]
        if digest({k: v for k, v in result.items() if k != "experiment_id"}) != identity:
            raise ValueError("Artifact digest mismatch")
        raw = canonical(result).encode()
        fd, temporary = tempfile.mkstemp(dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.root / (identity + ".json"))
            except FileExistsError:
                if (self.root / (identity + ".json")).read_bytes() != raw:
                    raise ValueError("Immutable artifact conflict")
        finally:
            os.unlink(temporary)
        return identity

    def get(self, identity):
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ValueError("Invalid experiment ID")
        result = json.loads((self.root / (identity + ".json")).read_text())
        if result.get("experiment_id") != identity or digest({k: v for k, v in result.items() if k != "experiment_id"}) != identity:
            raise ValueError("Artifact integrity verification failed")
        return result

    def history(self):
        return [{k: result[k] for k in ("experiment_id", "status", "configuration", "dataset_sha256", "code_sha256", "event_count", "session_count")}
                for p in sorted(self.root.glob("*.json")) for result in [self.get(p.stem)]]


class Workspace:
    def __init__(self, store, *, demo=False, bundle=None):
        self.store, self.demo, self.bundle = Store(store), demo, bundle
        self.jobs, self.lock = {}, Lock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.adapter, self.partitions = demo_inputs() if demo else (None, {})

    def catalog(self):
        if self.demo:
            return {"mode": "SYNTHETIC SOFTWARE DEMONSTRATION", "strategy": SPEC,
                "contract": self.adapter.manifest.contract, "dataset_version": "synthetic-demo-v1",
                "sessions": [{"date": d, "partition": p, "eligible": p != "final_holdout"} for d, p in self.partitions.items()],
                "blocked": None, "strict_eligible": False}
        return {"mode": "HISTORICAL — STRICT CERTIFICATION REQUIRED", "strategy": SPEC,
            "contract": self.bundle.get("contract") if self.bundle else None,
            "dataset_version": self.bundle.get("dataset_version") if self.bundle else None,
            "sessions": [], "strict_eligible": False,
            "blocked": "Historical research requires independently accepted VWAP and signal certification, bound inputs and predeclared chronological partitions. Production acceptance pins are empty in this checkout."}

    def execute(self, config):
        adapter, partitions = self.adapter, self.partitions
        if not self.demo:
            if not self.bundle:
                raise ValueError("BLOCKED: v2.0.0 dataset and accepted certification bundle are not installed")
            b = self.bundle
            # Both gates run BEFORE opening dataset/calendar bytes. Never admit
            # historical inputs via the exploratory adapter as a gate bypass.
            for profile in ("VWAP", "signal"):
                require_strict_dataset(b["dataset_path"], b["certification_manifest"], instrument="NQ", research=profile)
            manifest = load_manifest(b["exploratory_manifest"])
            data = Path(b["dataset_path"]).read_bytes()
            calendar = Path(b["calendar_path"]).read_bytes()
            bars = []
            for record in decode_dataset_bars(data):
                r = dict(record)
                r["timestamp"] = parse(r["timestamp"])
                r["duration"] = timedelta(seconds=r.pop("duration_seconds"))
                bars.append(Bar(**r))
            adapter = ReadOnlyExploratoryAdapter(manifest, bars, dataset_bytes=data, calendar_bytes=calendar)
            partitions = b["partitions"]
        provenance = {"dataset_version": "synthetic-demo-v1" if self.demo else self.bundle["dataset_version"],
            "source": "formula-constructed software fixture" if self.demo else adapter.manifest.dataset_id,
            "eligibility_manifest_reference": "sha256:" + digest({"manifest": adapter.manifest.to_dict(), "partitions": partitions}),
            "eligibility_manifest": adapter.manifest.to_dict(), "partition_manifest": partitions,
            "classification": "SYNTHETIC" if self.demo else "HISTORICAL",
            "availability": "retrospective bar-close assumption; not independently certified publication evidence",
            "certification_policy": "canonical-market-data-v1.0.0; trust roots unchanged"}
        result = run(adapter, partitions, config, provenance)
        self.store.put(result)
        return result["experiment_id"]

    def submit(self, config):
        identity = uuid4().hex
        with self.lock:
            if any(job["status"] in {"queued", "running"} for job in self.jobs.values()):
                raise ValueError("One experiment at a time; wait for the current job")
            self.jobs[identity] = {"job_id": identity, "status": "queued"}
        def work():
            with self.lock:
                self.jobs[identity]["status"] = "running"
            try:
                result = self.execute(config)
                update = {"status": "completed", "experiment_id": result}
            except Exception as error:
                update = {"status": "blocked" if not self.demo or "holdout" in str(error).lower() else "failed", "error": str(error)}
            with self.lock:
                self.jobs[identity].update(update)
        self.pool.submit(work)
        return identity

    def close(self):
        self.pool.shutdown(wait=True)


def make_server(workspace, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, value, status=200, content_type="application/json"):
            body = canonical(value).encode() if content_type == "application/json" else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def safe_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            if not self.safe_host():
                return self.send({"error": "Loopback host required"}, 403)
            url = urlparse(self.path.replace("/api/research/", "/api/", 1).replace("/research/", "/", 1))
            try:
                if url.path == "/api/catalog":
                    return self.send(workspace.catalog())
                if url.path == "/api/experiments":
                    return self.send(workspace.store.history())
                if url.path.startswith("/api/jobs/"):
                    with workspace.lock:
                        return self.send(dict(workspace.jobs[url.path.rsplit("/", 1)[-1]]))
                if url.path.startswith("/api/experiments/"):
                    result = workspace.store.get(url.path.rsplit("/", 1)[-1])
                    params = parse_qs(url.query, keep_blank_values=True)
                    if set(params) - {"as_of"}:
                        raise ValueError("Unknown result query")
                    return self.send(replay_view(result, params.get("as_of", [None])[0]))
                assets = {"/": (HERE / "index.html", "text/html; charset=utf-8"),
                    "/app.js": (HERE / "app.js", "text/javascript"),
                    "/charts.js": (HERE.parent / "vendor/lightweight-charts-5.1.0.js", "text/javascript")}
                if url.path in assets:
                    path, kind = assets[url.path]
                    return self.send(path.read_bytes(), content_type=kind)
                return self.send({"error": "Not found"}, 404)
            except (ValueError, KeyError, FileNotFoundError) as error:
                return self.send({"error": str(error)}, 400)

        def do_POST(self):
            if not self.safe_host() or self.headers.get("Origin") not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
                return self.send({"error": "Same-origin loopback request required"}, 403)
            if self.path not in {"/api/experiments", "/api/research/experiments"}:
                return self.send({"error": "Not found"}, 404)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    raise ValueError("Invalid request size")
                if self.headers.get("Content-Type") != "application/json":
                    raise ValueError("JSON required")
                config = json.loads(self.rfile.read(size))
                if not isinstance(config, dict):
                    raise ValueError("Configuration object required")
                return self.send({"job_id": workspace.submit(config)}, 202)
            except (ValueError, TypeError) as error:
                return self.send({"error": str(error)}, 400)
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="explicit synthetic software test mode")
    parser.add_argument("--bundle", type=Path, help="administrator-owned historical bundle JSON")
    parser.add_argument("--store", type=Path, default=Path("results/terminal"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.demo and args.bundle:
        parser.error("Choose demo OR historical bundle")
    workspace = Workspace(args.store, demo=args.demo, bundle=json.loads(args.bundle.read_text()) if args.bundle else None)
    server = make_server(workspace, args.port)
    print(f"NQ Research Terminal v0.3: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        workspace.close()


if __name__ == "__main__":
    main()
