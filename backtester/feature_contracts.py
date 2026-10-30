"""Point-in-time feature contracts.

A contract is accepted only when every input used at the decision was available
at or before that decision. Missing evidence fails closed.
"""
from __future__ import annotations

from datetime import datetime, timedelta

FEATURE_SCHEMA_VERSION = "feature-contract-v1.0.0"
_FIELDS = (
    "schema_version",
    "feature_id",
    "observation_timestamp",
    "source_publication_timestamp",
    "data_availability_timestamp",
    "decision_timestamp",
    "lookback",
    "revision_policy",
    "adjustment_policy",
    "missing_data_policy",
    "required_evidence",
    "revisions",
)


class FeatureContractError(ValueError):
    pass


def parse_utc(value, label):
    if not isinstance(value, str) or not value:
        raise FeatureContractError(f"{label} timestamp must be a UTC string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FeatureContractError(f"{label} timestamp is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise FeatureContractError(f"{label} timestamp must be UTC")
    return parsed


def validate_feature_contract(contract):
    """Return the contract when its timestamps cannot leak into the decision."""
    if not isinstance(contract, dict) or set(contract) != set(_FIELDS):
        raise FeatureContractError("feature contract fields do not match feature-contract-v1.0.0")
    if contract["schema_version"] != FEATURE_SCHEMA_VERSION or not contract["feature_id"]:
        raise FeatureContractError("unsupported feature contract schema or feature id")
    if contract["revision_policy"] != "reject_revisions":
        raise FeatureContractError("revision policy must reject revisions")
    if contract["adjustment_policy"] != "raw_unadjusted":
        raise FeatureContractError("adjustment policy must stay raw and unadjusted")
    if contract["missing_data_policy"] != "fail_closed":
        raise FeatureContractError("missing-data policy must fail closed")
    required = contract["required_evidence"]
    if not isinstance(required, list) or not required or any(not isinstance(item, str) or not item for item in required):
        raise FeatureContractError("required evidence must name at least one source")
    lookback = contract["lookback"]
    if (not isinstance(lookback, dict) or type(lookback.get("bars")) is not int or lookback["bars"] < 1
            or type(lookback.get("bar_seconds")) is not int or lookback["bar_seconds"] < 1):
        raise FeatureContractError("lookback window must be a positive number of bars and seconds")
    if contract["data_availability_timestamp"] is None:
        raise FeatureContractError("missing data availability timestamp")
    if "source_publication" in required and contract["source_publication_timestamp"] is None:
        raise FeatureContractError("missing publication evidence")
    decision = parse_utc(contract["decision_timestamp"], "decision")
    availability = parse_utc(contract["data_availability_timestamp"], "data availability")
    observation = parse_utc(contract["observation_timestamp"], "observation")
    if availability > decision:
        raise FeatureContractError("data availability timestamp is after the decision timestamp")
    publication = contract["source_publication_timestamp"]
    if publication is not None:
        published = parse_utc(publication, "source publication")
        if published > decision or published > availability:
            raise FeatureContractError("delayed publication is after the decision or availability timestamp")
    window_start = decision - timedelta(seconds=lookback["bars"] * lookback["bar_seconds"])
    if observation > decision:
        raise FeatureContractError("observation timestamp is after the decision timestamp")
    if observation < window_start:
        raise FeatureContractError("observation timestamp is outside the lookback window")
    revisions = contract["revisions"]
    if not isinstance(revisions, list):
        raise FeatureContractError("revisions must be a list")
    if contract["revision_policy"] == "reject_revisions" and revisions:
        raise FeatureContractError("revision is not eligible under reject_revisions")
    for revision in revisions:
        if not isinstance(revision, dict) or "revised_at" not in revision:
            raise FeatureContractError("revision is missing revised_at")
        revised_at = parse_utc(revision["revised_at"], "revision")
        if revised_at > decision:
            raise FeatureContractError("revision after the decision timestamp is leakage")
    return contract
