"""
Storage twin.

The core "digital twin" for a storage unit (cold storage, warehouse, silo,
etc.). Owns environmental breach detection and produces the "environmental
stress factor" that produce_twin.py uses to accelerate or slow decay
simulation. Pure in-memory logic - never touches the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.models.storage import StorageUnit, StorageReading


@dataclass
class BreachInfo:
    is_breached: bool
    dimension: Optional[str] = None  # "temperature" | "humidity"
    deviation: Optional[float] = None
    message: Optional[str] = None


class StorageTwin:
    """Wraps a StorageUnit ORM instance with environment health computation."""

    def __init__(self, storage: StorageUnit):
        self.storage = storage

    @classmethod
    def from_model(cls, storage: StorageUnit) -> "StorageTwin":
        return cls(storage)

    # ---------------------------------------------------------------
    # Capacity
    # ---------------------------------------------------------------

    def utilization_pct(self) -> float:
        if not self.storage.capacity_kg:
            return 0.0
        return round((self.storage.current_load_kg / self.storage.capacity_kg) * 100, 1)

    def available_capacity_kg(self) -> float:
        return max(0.0, self.storage.capacity_kg - self.storage.current_load_kg)

    def has_capacity_for(self, quantity_kg: float) -> bool:
        return self.available_capacity_kg() >= quantity_kg

    def is_near_full(self, threshold_pct: float = 90.0) -> bool:
        return self.utilization_pct() >= threshold_pct

    # ---------------------------------------------------------------
    # Environmental breach detection
    # ---------------------------------------------------------------

    def temperature_breach(self) -> BreachInfo:
        temp = self.storage.current_temperature_c
        lo, hi = self.storage.ideal_temp_min_c, self.storage.ideal_temp_max_c

        if temp is None or (lo is None and hi is None):
            return BreachInfo(is_breached=False)

        if hi is not None and temp > hi:
            return BreachInfo(
                True, "temperature", round(temp - hi, 2),
                f"{temp}\u00b0C exceeds ideal max {hi}\u00b0C",
            )
        if lo is not None and temp < lo:
            return BreachInfo(
                True, "temperature", round(lo - temp, 2),
                f"{temp}\u00b0C is below ideal min {lo}\u00b0C",
            )
        return BreachInfo(is_breached=False)

    def humidity_breach(self) -> BreachInfo:
        humidity = self.storage.current_humidity_pct
        lo, hi = self.storage.ideal_humidity_min_pct, self.storage.ideal_humidity_max_pct

        if humidity is None or (lo is None and hi is None):
            return BreachInfo(is_breached=False)

        if hi is not None and humidity > hi:
            return BreachInfo(
                True, "humidity", round(humidity - hi, 2),
                f"{humidity}% exceeds ideal max {hi}%",
            )
        if lo is not None and humidity < lo:
            return BreachInfo(
                True, "humidity", round(lo - humidity, 2),
                f"{humidity}% is below ideal min {lo}%",
            )
        return BreachInfo(is_breached=False)

    def has_environment_breach(self) -> bool:
        return self.temperature_breach().is_breached or self.humidity_breach().is_breached

    def active_breaches(self) -> list[BreachInfo]:
        return [b for b in (self.temperature_breach(), self.humidity_breach()) if b.is_breached]

    # ---------------------------------------------------------------
    # Decay influence
    # ---------------------------------------------------------------

    def environmental_stress_factor(self) -> float:
        """Multiplier applied to a produce batch's base decay rate.
        1.0 = ideal conditions, >1.0 = accelerated decay, capped to keep
        simulation results sane."""

        factor = 1.0

        temp_breach = self.temperature_breach()
        if temp_breach.is_breached and temp_breach.deviation:
            factor += min(2.0, temp_breach.deviation * 0.1)

        humidity_breach = self.humidity_breach()
        if humidity_breach.is_breached and humidity_breach.deviation:
            factor += min(1.0, humidity_breach.deviation * 0.02)

        return round(factor, 3)

    # ---------------------------------------------------------------
    # Sensor ingestion
    # ---------------------------------------------------------------

    def ingest_reading(self, reading: StorageReading) -> None:
        """Update the storage unit's live snapshot fields from a new sensor
        reading and flag it as anomalous if it breaches ideal ranges.
        Caller (a service) is responsible for persisting both objects."""

        if reading.temperature_c is not None:
            self.storage.current_temperature_c = reading.temperature_c
        if reading.humidity_pct is not None:
            self.storage.current_humidity_pct = reading.humidity_pct
        if reading.co2_ppm is not None:
            self.storage.current_co2_ppm = reading.co2_ppm
        if reading.ethylene_ppm is not None:
            self.storage.current_ethylene_ppm = reading.ethylene_ppm

        reading.is_anomalous = self.has_environment_breach()
        if reading.is_anomalous and not reading.anomaly_reason:
            reasons = [b.message for b in self.active_breaches() if b.message]
            reading.anomaly_reason = "; ".join(reasons)

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "storage_id": self.storage.id,
            "name": self.storage.name,
            "storage_type": self.storage.storage_type.value,
            "utilization_pct": self.utilization_pct(),
            "available_capacity_kg": self.available_capacity_kg(),
            "current_temperature_c": self.storage.current_temperature_c,
            "current_humidity_pct": self.storage.current_humidity_pct,
            "has_breach": self.has_environment_breach(),
            "breach_messages": [b.message for b in self.active_breaches() if b.message],
            "environmental_stress_factor": self.environmental_stress_factor(),
            "as_of": datetime.now(timezone.utc).isoformat(),
        }