"""Independently approved evidence registry (QUA-24 / QUA-25).

Production authorization lives ONLY in reviewed, version-controlled
configuration: ``config/approved_evidence.json`` at the repository root.
A caller cannot authorize evidence by supplying its hash, and an artifact
plus a matching caller-computed hash is not sufficient: the hash must
already be present in the registry, associated (for ledgers) with the
pinned calendar identity. An empty registry is valid and fails closed.

Adding an approval is a separate human-reviewed change to that JSON file
(and, for a capture/ledger to be usable, to nothing else at call time).
Synthetic/test fixtures must never be entered in the production registry;
tests use ``EvidenceRegistry.for_testing`` plumbing registries instead,
which production gates (the default, registry-less calls) reject.

This module is standalone (no backtester imports) to avoid cycles.
"""
from dataclasses import dataclass
import json
import re
from pathlib import Path

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_MARKERS = ("synthetic", "fixture", "test", "fake", "forged", "fabricated")


def _hex64(value, field):
    if not isinstance(value, str) or not _HEX64.match(value):
        raise ValueError(f"Approved evidence registry entry has invalid {field}")
    return value


def _check_label(value, field="label"):
    if value is None:
        return
    text = str(value).lower()
    if any(marker in text for marker in _FORBIDDEN_MARKERS):
        raise ValueError(
            "Synthetic/test fixtures must never be authorized in the evidence registry "
            f"({field}={value!r})")
    return


@dataclass(frozen=True)
class CaptureManifestApproval:
    manifest_sha256: str
    label: object = None
    provider: object = None
    dataset: object = None


@dataclass(frozen=True)
class CertificationLedgerApproval:
    ledger_sha256: str
    calendar_file_sha256: str
    calendar_document_sha256: str
    certification_version: str
    label: object = None


@dataclass(frozen=True)
class EvidenceRegistry:
    capture_manifests: tuple = ()
    certification_ledgers: tuple = ()
    source: str = "production"

    # -- constructors -----------------------------------------------------
    @classmethod
    def empty(cls, source="production"):
        return cls((), (), source)

    @classmethod
    def for_testing(cls, capture_manifest_sha256s=(), certification_ledgers=()):
        """Test-plumbing registry. NOT production authorization.

        ``certification_ledgers`` items are dicts with ledger_sha256,
        calendar_file_sha256, calendar_document_sha256 and
        certification_version. Production gates never consult a registry
        built here unless a test explicitly passes it via ``_test_registry``.
        """
        captures = tuple(
            entry if isinstance(entry, CaptureManifestApproval)
            else CaptureManifestApproval(_hex64(entry, "manifest_sha256"))
            for entry in capture_manifest_sha256s)
        ledgers = []
        for entry in certification_ledgers:
            if isinstance(entry, CertificationLedgerApproval):
                ledgers.append(entry)
            else:
                ledgers.append(CertificationLedgerApproval(
                    _hex64(entry["ledger_sha256"], "ledger_sha256"),
                    _hex64(entry["calendar_file_sha256"], "calendar_file_sha256"),
                    _hex64(entry["calendar_document_sha256"], "calendar_document_sha256"),
                    str(entry["certification_version"])))
        registry = cls(captures, tuple(ledgers), "test")
        registry._validate()
        return registry

    @classmethod
    def from_file(cls, path, source="file"):
        raw = Path(path).read_bytes()
        try:
            document = json.loads(raw)
        except Exception as error:
            raise ValueError("Approved evidence registry is not valid JSON") from error
        if not isinstance(document, dict) or document.get("version") != 1:
            raise ValueError("Approved evidence registry requires version 1")
        if set(document) - {"version", "capture_manifests", "certification_ledgers"}:
            raise ValueError("Approved evidence registry has unknown fields")
        captures = []
        for entry in document.get("capture_manifests") or []:
            if not isinstance(entry, dict):
                raise ValueError("Capture manifest approval must be an object")
            _check_label(entry.get("label"))
            _check_label(entry.get("approval_id"), "approval_id")
            captures.append(CaptureManifestApproval(
                _hex64(entry.get("manifest_sha256"), "manifest_sha256"),
                label=entry.get("label"), provider=entry.get("provider"),
                dataset=entry.get("dataset")))
        ledgers = []
        for entry in document.get("certification_ledgers") or []:
            if not isinstance(entry, dict):
                raise ValueError("Certification ledger approval must be an object")
            _check_label(entry.get("label"))
            _check_label(entry.get("approval_id"), "approval_id")
            version = entry.get("certification_version")
            if not isinstance(version, str) or not version:
                raise ValueError("Certification ledger approval requires a certification version")
            ledgers.append(CertificationLedgerApproval(
                _hex64(entry.get("ledger_sha256"), "ledger_sha256"),
                _hex64(entry.get("calendar_file_sha256"), "calendar_file_sha256"),
                _hex64(entry.get("calendar_document_sha256"), "calendar_document_sha256"),
                version, label=entry.get("label")))
        registry = cls(tuple(captures), tuple(ledgers), source)
        registry._validate()
        return registry

    def _validate(self):
        capture_hashes = [c.manifest_sha256 for c in self.capture_manifests]
        if len(set(capture_hashes)) != len(capture_hashes):
            raise ValueError("Duplicate capture manifest approvals in evidence registry")
        ledger_hashes = [entry.ledger_sha256 for entry in self.certification_ledgers]
        if len(set(ledger_hashes)) != len(ledger_hashes):
            raise ValueError("Duplicate certification ledger approvals in evidence registry")
        for entry in self.capture_manifests:
            _hex64(entry.manifest_sha256, "manifest_sha256")
        for entry in self.certification_ledgers:
            _hex64(entry.ledger_sha256, "ledger_sha256")
            _hex64(entry.calendar_file_sha256, "calendar_file_sha256")
            _hex64(entry.calendar_document_sha256, "calendar_document_sha256")

    # -- queries ----------------------------------------------------------
    def capture_approved(self, manifest_sha256, provider=None, dataset=None):
        for entry in self.capture_manifests:
            if entry.manifest_sha256 != manifest_sha256:
                continue
            if entry.provider is not None and provider is not None and entry.provider != provider:
                continue
            if entry.dataset is not None and dataset is not None and entry.dataset != dataset:
                continue
            return True
        return False

    def ledger_approved(self, ledger_sha256, calendar_file_sha256,
                        calendar_document_sha256, certification_version):
        return any(
            entry.ledger_sha256 == ledger_sha256
            and entry.calendar_file_sha256 == calendar_file_sha256
            and entry.calendar_document_sha256 == calendar_document_sha256
            and entry.certification_version == certification_version
            for entry in self.certification_ledgers)


def production_registry_path():
    return Path(__file__).resolve().parents[1] / "config" / "approved_evidence.json"


def load_production_registry():
    """Load the reviewed, version-controlled production registry.

    A missing or empty registry fails closed (authorizes nothing); a
    malformed registry raises rather than silently authorizing anything.
    """
    path = production_registry_path()
    if not path.exists():
        return EvidenceRegistry.empty(source="production-missing")
    return EvidenceRegistry.from_file(path, source="production")


def resolve_registry(test_registry=None):
    """Effective registry: explicit test plumbing, else production config."""
    return test_registry if test_registry is not None else load_production_registry()
