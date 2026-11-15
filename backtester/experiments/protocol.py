"""Versioned synthetic experiment definitions. This registry has no price source inputs."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import tomllib


FAMILY = tuple(f"H{number}" for number in range(1, 11))


@dataclass(frozen=True)
class Protocol:
    id: str = "H4"
    revision: str = "1.0.0"
    stage: str = "synthetic"
    title: str = "Opening range acceptance continues"
    instrument: str = "NQ"
    timezone: str = "America/New_York"
    cash_open: str = "09:30"
    cash_close: str = "16:00"
    opening_minutes: int = 30
    scan_through: str = "11:27"
    outside_ticks: int = 1
    confirmation_bars: int = 2
    hold_minutes: int = 30
    delay_minutes: int = 1
    round_trip_fee_cents: int = 500
    bootstrap_draws: int = 10_000
    block_lengths: tuple[int, ...] = (5, 2, 10, 20)
    seed: int = 401
    amendments_pending: tuple[str, ...] = ("A1", "A2", "A3", "A4", "A5", "A6")


@dataclass(frozen=True)
class Registry:
    schema_version: int
    family: tuple[str, ...]
    definitions: tuple[Protocol, ...]
    source_sha256: str

    def get(self, experiment_id: str, revision: str) -> Protocol:
        for definition in self.definitions:
            if (definition.id, definition.revision) == (experiment_id, revision):
                return definition
        raise ValueError(f"Unknown experiment revision {experiment_id}@{revision}")


def load_registry(path: Path) -> Registry:
    content = path.read_bytes()
    raw = tomllib.loads(content.decode("utf-8"))
    if set(raw) != {"schema_version", "family", "experiments"}:
        raise ValueError("Unexpected registry fields")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("Unsupported registry schema")
    if raw["family"] != list(FAMILY):
        raise ValueError("Family must include the ten original slots in order")
    if not isinstance(raw["experiments"], list) or not raw["experiments"]:
        raise ValueError("Registry must contain experiment definitions")

    supported = {("H4", "1.0.0"): Protocol()}
    definitions = {}
    for entry in raw["experiments"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid experiment definition")
        if entry.get("stage") != "synthetic":
            raise ValueError("Only synthetic definitions are enabled")
        key = (entry.get("id"), entry.get("revision"))
        if any(type(value) is not str for value in key) or key not in supported:
            raise ValueError("Unsupported experiment revision")
        if key in definitions:
            raise ValueError("Duplicate experiment revision")
        definition = supported[key]
        expected = asdict(definition)
        for field in ("block_lengths", "amendments_pending"):
            expected[field] = list(expected[field])
        # Check types recursively so TOML booleans and floats cannot stand in for ints.
        if entry.keys() != expected.keys() or any(
            type(entry[name]) is not type(value) or repr(entry[name]) != repr(value)
            for name, value in expected.items()
        ):
            raise ValueError(f"Definition fields differ from frozen revision {key}")
        definitions[key] = definition
    return Registry(1, FAMILY, tuple(definitions.values()), sha256(content).hexdigest())
