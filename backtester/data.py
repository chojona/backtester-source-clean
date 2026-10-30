"""Immutable intraday bars and provider-independent validated CSV ingestion."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
import hashlib
import json
import math
from .instruments import contract_root, instrument


_VERIFIED_OI_TOKEN = object()


def _aware(value):
    """Aware datetime or None; invalid tzinfo objects never raise (QUA-24)."""
    if not isinstance(value, datetime):
        return None
    try:
        if value.utcoffset() is None:
            return None
    except Exception:
        return None
    return value


@dataclass(frozen=True)
class OpenInterestCaptureReceipt:
    """Deprecated caller-supplied receipt. NEVER authoritative (QUA-24).

    A receipt object is just caller-written values. It cannot mint causal
    evidence: ``verify_open_interest_capture`` refuses it. Trusted OI is
    re-derived from hash-checked raw capture artifacts and request manifests
    by ``verify_open_interest_from_capture_artifacts`` (generic captures) or
    the Databento raw-directory path in ``providers.databento``.
    """
    provider: object = None
    dataset: object = None
    request_id: object = None
    instrument_id: object = None
    source_ts_event_ns: object = None
    source_ts_recv_ns: object = None
    quantity: object = None
    receipt_id: object = None


def _ns_to_utc(ns):
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=(int(ns) + 999) // 1000)


def _verified_digest(v):
    payload = dict(available_at=_aware(v.available_at).isoformat() if _aware(v.available_at) else None,
                   quantity=v.quantity, provider=v.provider, dataset=v.dataset,
                   request_id=v.request_id, instrument_id=v.instrument_id,
                   contract=v.contract, bar_timestamp=_aware(v.bar_timestamp).isoformat() if _aware(v.bar_timestamp) else None,
                   bar_source_ts_event_ns=v.bar_source_ts_event_ns,
                   oi_source_ts_event_ns=v.oi_source_ts_event_ns,
                   oi_source_ts_recv_ns=v.oi_source_ts_recv_ns,
                   capture_manifest_sha256=v.capture_manifest_sha256,
                   capture_artifact_sha256=v.capture_artifact_sha256, receipt_id=v.receipt_id)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class VerifiedOpenInterest:
    """OI re-derived from hash-checked capture artifacts (QUA-24).

    Bound to provider, dataset, request, instrument, contract, the exact
    bar timestamp and bar event timestamp, the OI event/receipt timestamps,
    quantity, capture (availability) time, and the hashes of the manifest
    and artifact file it was re-derived from. The token/digest are
    consistency checks only, NOT a cryptographic boundary: the boundary is
    re-derivation against artifacts whose manifest hash is approved in
    the reviewed evidence registry (config/approved_evidence.json), plus
    the downstream registry recheck in rolls.causal_open_interest. See
    ``docs/provenance-trust-chain.md``.
    """
    available_at: object
    quantity: object
    provider: object
    dataset: object
    request_id: object
    instrument_id: object
    receipt_id: object
    contract: object = None
    bar_timestamp: object = None
    bar_source_ts_event_ns: object = None
    oi_source_ts_event_ns: object = None
    oi_source_ts_recv_ns: object = None
    capture_manifest_sha256: object = None
    capture_artifact_sha256: object = None
    binding_sha256: object = None
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _VERIFIED_OI_TOKEN:
            raise ValueError("Verified OI must be re-derived from hash-checked capture artifacts")
        if not self.contract or _aware(self.bar_timestamp) is None \
                or not isinstance(self.capture_manifest_sha256, str) or len(self.capture_manifest_sha256) != 64 \
                or not isinstance(self.capture_artifact_sha256, str) or len(self.capture_artifact_sha256) != 64:
            raise ValueError("Verified OI requires contract, bar timestamp and capture artifact hashes")
        try:
            expected_available = _ns_to_utc(max(int(self.oi_source_ts_event_ns), int(self.oi_source_ts_recv_ns)))
        except Exception as error:
            raise ValueError("Verified OI requires OI event/receipt timestamps") from error
        if _aware(self.available_at) != expected_available:
            raise ValueError("Verified OI availability does not match its capture timestamps")
        if self.binding_sha256 != _verified_digest(self):
            raise ValueError("Verified OI binding digest does not match its bound fields")


def _mint_verified_open_interest(bar, *, oi_source_ts_event_ns, oi_source_ts_recv_ns,
                                 capture_manifest_sha256, capture_artifact_sha256, receipt_id):
    """Internal mint: call ONLY after re-deriving OI from hash-checked artifacts.

    This helper is not itself a security boundary; callers must first verify
    artifact hashes against a registry-approved manifest hash and
    re-derive quantity/identity from the artifact contents.
    """
    try:
        event_ns, recv_ns = int(oi_source_ts_event_ns), int(oi_source_ts_recv_ns)
    except (TypeError, ValueError) as error:
        raise ValueError("Capture evidence requires event/receipt nanosecond timestamps") from error
    if event_ns <= 0 or recv_ns <= 0 or bar.open_interest is None:
        raise ValueError("Capture evidence requires positive timestamps and a bar OI quantity")
    if bar.open_interest_state not in (None, "CAUSAL_CAPTURE_BOUND"):
        raise ValueError("Declaring a non-causal OI state cannot be upgraded by capture evidence")
    available = _ns_to_utc(max(event_ns, recv_ns))
    declared = bar.open_interest_available_at
    if declared is not None and _aware(declared) != available:
        raise ValueError("Declared OI availability does not match re-derived capture evidence")
    from types import SimpleNamespace
    digest = _verified_digest(SimpleNamespace(
        available_at=available, quantity=bar.open_interest, provider=bar.provider,
        dataset=bar.dataset, request_id=bar.request_id, instrument_id=bar.instrument_id,
        contract=bar.contract, bar_timestamp=bar.timestamp,
        bar_source_ts_event_ns=bar.source_ts_event_ns, oi_source_ts_event_ns=event_ns,
        oi_source_ts_recv_ns=recv_ns, capture_manifest_sha256=capture_manifest_sha256,
        capture_artifact_sha256=capture_artifact_sha256, receipt_id=receipt_id))
    verified = VerifiedOpenInterest(available, bar.open_interest, bar.provider, bar.dataset,
                                    bar.request_id, bar.instrument_id, receipt_id,
                                    contract=bar.contract, bar_timestamp=bar.timestamp,
                                    bar_source_ts_event_ns=bar.source_ts_event_ns,
                                    oi_source_ts_event_ns=event_ns, oi_source_ts_recv_ns=recv_ns,
                                    capture_manifest_sha256=capture_manifest_sha256,
                                    capture_artifact_sha256=capture_artifact_sha256,
                                    binding_sha256=digest, _token=_VERIFIED_OI_TOKEN)
    return replace(bar, open_interest_available_at=available,
                   open_interest_state="CAUSAL_CAPTURE_BOUND",
                   open_interest_verification=verified)


def verify_open_interest_capture(bar, receipt):
    """Refused: a caller-supplied receipt cannot mint causal OI (QUA-24 H2-A).

    Previously this bound a caller-created Bar to a caller-created receipt
    with matching fields, so any ordinary caller could forge authoritative
    evidence. Use ``verify_open_interest_from_capture_artifacts`` or the
    Databento raw-directory path instead.
    """
    raise ValueError("Caller-supplied OI receipts are not authoritative; causal OI must be "
                     "re-derived from hash-checked raw capture artifacts and request manifests")


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_open_interest_from_capture_artifacts(bar, capture_directory, *, expected_manifest_sha256=None, _test_registry=None):
    """Re-derive trusted OI for ``bar`` from hash-checked capture artifacts.

    Production authorization comes ONLY from the approved evidence
    registry (``config/approved_evidence.json``, loaded by default): the
    manifest hash must already be approved there, associated with the
    capture identity. ``expected_manifest_sha256`` is at most a
    consistency check -- a caller-supplied hash (including a correctly
    computed hash of fabricated artifacts) can never authorize evidence.
    ``_test_registry`` is synthetic plumbing for tests only and is never
    used by production callers. The manifest binds provider, dataset and
    request_id and lists artifact file hashes; the observations file it
    names is hash-checked, then the single observation for this bar's
    exact contract, instrument, bar timestamp and bar event timestamp
    supplies quantity and OI event/receipt timestamps. Any mismatch,
    replay across contracts/events, missing registry approval, or missing
    evidence raises and leaves the bar unverified (selection unresolved).
    This checks consistency against approved hashes; it is not
    cryptographic proof of provider origin.
    """
    from .evidence_registry import resolve_registry
    root = Path(capture_directory)
    manifest_path = root / "manifest.json"
    actual_manifest_sha256 = _sha256_file(manifest_path)
    if expected_manifest_sha256 is not None:
        if not isinstance(expected_manifest_sha256, str) or len(expected_manifest_sha256) != 64:
            raise ValueError("Causal OI requires an independently pinned capture manifest SHA-256")
        if actual_manifest_sha256 != expected_manifest_sha256:
            raise ValueError("Capture manifest hash does not match the independently pinned hash")
    registry = resolve_registry(_test_registry)
    if not registry.capture_approved(actual_manifest_sha256, provider=bar.provider, dataset=bar.dataset):
        raise ValueError("Capture manifest is not in the approved evidence registry; "
                         "a caller-supplied hash cannot authorize causal OI")
    expected_manifest_sha256 = actual_manifest_sha256
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("capture_complete") is not True:
        raise ValueError("Capture manifest does not establish a complete capture")
    if (manifest.get("provider"), manifest.get("dataset"), manifest.get("request_id")) != \
            (bar.provider, bar.dataset, bar.request_id):
        raise ValueError("Capture manifest identity does not match the bar")
    files = manifest.get("files") or {}
    observations_name = manifest.get("observations_file", "observations.jsonl")
    if Path(observations_name).name != observations_name or observations_name not in files:
        raise ValueError("Capture manifest lacks a hashed observations artifact")
    artifact_path = root / observations_name
    artifact_sha = _sha256_file(artifact_path)
    if artifact_sha != files[observations_name]:
        raise ValueError("Capture artifact hash mismatch")
    for name, digest in files.items():
        if Path(name).name != name or _sha256_file(root / name) != digest:
            raise ValueError("Capture artifact hash mismatch")
    matches = []
    for line in artifact_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if (row.get("contract"), row.get("instrument_id"), row.get("provider"),
                row.get("dataset"), row.get("request_id")) == \
                (bar.contract, bar.instrument_id, bar.provider, bar.dataset, bar.request_id) \
                and row.get("bar_timestamp") == bar.timestamp.isoformat() \
                and row.get("bar_source_ts_event_ns") == bar.source_ts_event_ns:
            matches.append(row)
    if len(matches) != 1:
        raise ValueError("Capture artifacts contain no unique OI observation for this exact bar/event")
    row = matches[0]
    if row.get("quantity") != bar.open_interest:
        raise ValueError("Re-derived OI quantity does not match the bar")
    return _mint_verified_open_interest(
        bar, oi_source_ts_event_ns=row.get("oi_source_ts_event_ns"),
        oi_source_ts_recv_ns=row.get("oi_source_ts_recv_ns"),
        capture_manifest_sha256=expected_manifest_sha256, capture_artifact_sha256=artifact_sha,
        receipt_id=f"capture:{expected_manifest_sha256[:16]}:{observations_name}:{row.get('bar_source_ts_event_ns')}")


@dataclass(frozen=True)
class Bar:
    timestamp: datetime                 # bar OPEN timestamp, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    contract: str
    symbol: str
    duration: timedelta = timedelta(minutes=1)
    trade_count: object = None
    bid_volume: object = None
    ask_volume: object = None
    open_interest: object = None
    bar_state: str = "TRADED"
    coverage_state: str = "UNVERIFIED"
    provider: object = None
    dataset: object = None
    schema: object = None
    instrument_id: object = None
    raw_symbol: object = None
    source_ts_event_ns: object = None
    request_id: object = None
    coverage_evidence: object = None
    published: bool = True
    # Distinct from `timestamp` (observation/bar-open time): the verified time
    # this OI value became available (later of publication and ingestion for
    # capture-bound feeds). Decisions enforce it in rolls.causal_open_interest
    # for every provider; storage alone does not make OI causal.
    # Caller-DECLARED OI availability/state only. Never authoritative: a CSV
    # or custom provider can write these strings freely. Only
    # open_interest_verification (re-derived from hash-checked capture
    # artifacts) may influence a decision.
    open_interest_available_at: object = None
    open_interest_state: object = None
    open_interest_verification: object = None

    @property
    def end(self):
        return self.timestamp + self.duration

    def __post_init__(self):
        if _aware(self.timestamp) is None:
            raise ValueError("Timestamp must include a UTC offset; naive timestamps are rejected")
        try:
            object.__setattr__(self, "timestamp", self.timestamp.astimezone(timezone.utc))
        except Exception as error:
            raise ValueError("Timestamp has an invalid timezone") from error
        if self.duration.total_seconds() <= 0:
            raise ValueError("Bar duration must be positive")
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(math.isfinite(x) for x in values):
            raise ValueError("OHLCV must be finite")
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close, self.high):
            raise ValueError("Impossible OHLC")
        if self.volume < 0:
            raise ValueError("Negative volume")
        for name in ("trade_count", "bid_volume", "ask_volume", "open_interest"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("Invalid " + name)
        if contract_root(self.contract) != self.symbol:
            raise ValueError("Contract root does not match instrument")
        instrument(self.symbol)
        if self.bar_state not in ("TRADED", "NO_TRADE") or self.coverage_state not in ("UNVERIFIED", "PROVIDER_AVAILABLE", "UNKNOWN"):
            raise ValueError("Invalid bar/coverage state")
        if self.bar_state == "NO_TRADE":
            if self.volume != 0 or len({self.open, self.high, self.low, self.close}) != 1 or self.published or self.coverage_state != "PROVIDER_AVAILABLE":
                raise ValueError("NO_TRADE requires zero volume, flat known price, available coverage and unpublished provenance")
        if self.open_interest_available_at is not None:
            declared = _aware(self.open_interest_available_at)
            if declared is None:
                raise ValueError("Open interest availability must be a timezone-aware datetime")
            try:
                if declared > self.timestamp:
                    raise ValueError("Open interest is not yet available at this bar")
            except ValueError:
                raise
            except Exception as error:
                raise ValueError("Open interest availability has an invalid timezone") from error
        if self.open_interest_verification is not None:
            verified = self.open_interest_verification
            if not isinstance(verified, VerifiedOpenInterest):
                raise ValueError("Open interest verification must be re-derived from capture artifacts")
            if verified.quantity != self.open_interest or verified.provider != self.provider \
                    or verified.dataset != self.dataset or verified.request_id != self.request_id \
                    or verified.instrument_id != self.instrument_id \
                    or verified.contract != self.contract \
                    or _aware(verified.bar_timestamp) != _aware(self.timestamp) \
                    or verified.bar_source_ts_event_ns != self.source_ts_event_ns \
                    or _aware(verified.available_at) is None \
                    or verified.binding_sha256 != _verified_digest(verified) \
                    or (self.open_interest_available_at is not None
                        and _aware(self.open_interest_available_at) != verified.available_at):
                raise ValueError("Open interest verification does not bind to this bar")


@dataclass
class IntegrityReport:
    rows: int = 0
    contracts: list = field(default_factory=list)
    missing_intervals: list = field(default_factory=list)
    off_tick_prices: int = 0
    warnings: list = field(default_factory=list)


class DataProvider(ABC):
    @abstractmethod
    def load(self):
        """Return (immutable chronological bars, integrity report)."""


def validate(bars, calendar):
    if not bars:
        raise ValueError("No bars")
    report = IntegrityReport(rows=len(bars), contracts=sorted({b.contract for b in bars}))
    previous_global, previous_contract = None, {}
    for bar in bars:
        if previous_global and bar.timestamp < previous_global:
            raise ValueError("Out-of-order timestamps")
        previous_global = bar.timestamp
        last = previous_contract.get(bar.contract)
        if last and bar.timestamp < last.end:
            raise ValueError("Duplicate or overlapping bars for " + bar.contract)
        if abs(bar.timestamp.timestamp() % bar.duration.total_seconds()) > 1e-8:
            raise ValueError("Timestamp not aligned to the configured bar interval")
        if not calendar.valid_bar(bar.timestamp, bar.duration):
            raise ValueError("Bar crosses a session boundary or occurs outside trading hours: " + bar.timestamp.isoformat())
        if last and bar.duration != last.duration:
            raise ValueError("Mixed intervals for " + bar.contract)
        if last:
            missing, first = 0, None
            probe = last.end
            while probe < bar.timestamp:
                if calendar.valid_bar(probe, bar.duration):
                    first = first or probe
                    missing += 1
                probe += bar.duration
            if probe != bar.timestamp:
                raise ValueError("Bars are not aligned to the configured interval")
            if missing:
                report.missing_intervals.append(dict(contract=bar.contract, start=first.isoformat(),
                                                     before=bar.timestamp.isoformat(), count=missing))
        ins = instrument(bar.symbol)
        if any(abs(ins.round_tick(p) - p) > 1e-8 for p in (bar.open, bar.high, bar.low, bar.close)):
            report.off_tick_prices += 1
        previous_contract[bar.contract] = bar
    report.warnings.extend(["Partial dataset boundaries are not treated as complete sessions.", calendar.source])
    if report.off_tick_prices:
        report.warnings.append("Off-tick prices found; may indicate adjusted or corrupted input")
    return report


class CSVProvider(DataProvider):
    def __init__(self, path, symbol, calendar, interval_minutes=1, contract=None):
        if interval_minutes not in (1, 5):
            raise ValueError("Initial CSV support is 1 or 5 minutes")
        self.path, self.symbol, self.calendar = Path(path), symbol, calendar
        self.interval, self.contract = timedelta(minutes=interval_minutes), contract

    def load(self):
        bars = []
        with self.path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            if not {"timestamp", "open", "high", "low", "close", "volume"}.issubset(reader.fieldnames or []):
                raise ValueError("CSV requires timestamp,open,high,low,close,volume")
            for line, row in enumerate(reader, 2):
                try:
                    contract = row.get("contract") or self.contract
                    if not contract:
                        raise ValueError("Dated contract is required; continuous inputs need constituent contracts")
                    if row.get("symbol") and row["symbol"] != self.symbol:
                        raise ValueError("Unexpected symbol")
                    optional = {key: float(row[key]) if row.get(key) else None
                                for key in ("trade_count", "bid_volume", "ask_volume", "open_interest")}
                    # Declared fields only: a CSV row can never create
                    # open_interest_verification, however it labels itself.
                    for key in ("bar_state", "coverage_state", "provider", "dataset", "schema", "raw_symbol", "request_id", "coverage_evidence", "open_interest_state"):
                        if row.get(key):
                            optional[key] = row[key]
                    for key in ("instrument_id", "source_ts_event_ns"):
                        if row.get(key):
                            optional[key] = int(row[key])
                    if row.get("published"):
                        if row["published"] not in ("True", "False"):
                            raise ValueError("Invalid published marker")
                        optional["published"] = row["published"] == "True"
                    if row.get("open_interest_available_at"):
                        optional["open_interest_available_at"] = datetime.fromisoformat(row["open_interest_available_at"])
                    bars.append(Bar(datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
                                    *(float(row[key]) for key in ("open", "high", "low", "close", "volume")),
                                    contract, self.symbol, self.interval, **optional))
                except (ValueError, TypeError) as error:
                    raise ValueError("CSV line {}: {}".format(line, error)) from error
        report = validate(bars, self.calendar)
        return tuple(bars), report
