"""Interfaces only: candle volume is NOT true exchange volume-at-price."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class VolumeProfile:
    vah: float
    val: float
    poc: float
    provenance: str          # TRUE_VOLUME_AT_PRICE or ESTIMATED_CANDLE
    algorithm: str
    timestamp: object

    def __post_init__(self):
        if self.provenance not in ("TRUE_VOLUME_AT_PRICE", "ESTIMATED_CANDLE"):
            raise ValueError("Volume profile provenance is required")


class ProfileProvider(ABC):
    @abstractmethod
    def snapshot(self, timestamp) -> VolumeProfile:
        """Use only trades or explicit estimated inputs available by timestamp."""
