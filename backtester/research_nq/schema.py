"""Exploratory dataset manifest schema (Python-embedded JSON Schema).

Embedded as a Python dict so the source-boundary checker does not need a new
JSON allowlist entry. Structural acceptance must match
``manifest.validate_manifest`` with and without the optional ``jsonschema``
dependency.
"""

SCHEMA_VERSION = "research-nq-exploratory-manifest-v1"

# Explicit UTC with trailing Z only (parity with Python validator).
_UTC_Z = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$"
# Non-empty after strip; no leading/trailing whitespace; maxLength enforced separately.
_NONEMPTY_STRIPPED = r"^\S(.*\S)?$"

EXPLORATORY_MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "research-nq-exploratory-manifest-v1",
    "title": "NQ exploratory dataset manifest",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "dataset_id",
        "dataset_sha256",
        "instrument",
        "contract",
        "time_range",
        "source",
        "coverage_classifications",
        "calendar_identity",
        "strict_eligible",
        "lane",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "dataset_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 256,
            "pattern": _NONEMPTY_STRIPPED,
        },
        "dataset_sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "content_sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "instrument": {"const": "NQ"},
        "contract": {
            "type": "string",
            "pattern": "^NQ[FGHJKMNQUVXZ][0-9]{1,2}$",
        },
        "time_range": {
            "type": "object",
            "additionalProperties": False,
            "required": ["start_utc", "end_utc"],
            "properties": {
                "start_utc": {"type": "string", "pattern": _UTC_Z},
                "end_utc": {"type": "string", "pattern": _UTC_Z},
            },
        },
        "source": {
            "type": "object",
            "additionalProperties": False,
            "required": ["provider", "locator", "acquisition_mode"],
            "properties": {
                "provider": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                    "pattern": _NONEMPTY_STRIPPED,
                },
                "locator": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1024,
                    "pattern": _NONEMPTY_STRIPPED,
                },
                "acquisition_mode": {
                    "enum": [
                        "synthetic_constructed",
                        "local_licensed_readonly",
                        "provider_capture_readonly",
                    ],
                },
                "notes": {
                    "type": "string",
                    "maxLength": 4096,
                },
            },
        },
        "coverage_classifications": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "enum": [
                    "observed",
                    "provider_inferred_no_trade",
                    "materialized",
                    "unresolved",
                ],
            },
        },
        "calendar_identity": {
            "type": "object",
            "additionalProperties": False,
            "required": ["calendar_id", "calendar_sha256"],
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                    "pattern": _NONEMPTY_STRIPPED,
                },
                "calendar_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "calendar_kind": {
                    "enum": [
                        "synthetic_test",
                        "dated_session",
                        "history_bridge",
                        "unpinned_local",
                    ],
                },
            },
        },
        "strict_eligible": {"const": False},
        "lane": {"const": "exploratory"},
        "limitations": {
            "type": "array",
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1024,
                "pattern": _NONEMPTY_STRIPPED,
            },
        },
    },
}
