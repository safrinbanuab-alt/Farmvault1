"""
storage_sensor.py
------------------
Simulates IoT sensors mounted inside storage facilities (cold storage rooms,
warehouses, open sheds) in FarmVault's digital twin.

Unlike `sensor_generator.py` (which tracks a single produce batch),
`storage_sensor.py` tracks the *environment* the produce sits in: ambient
temperature/humidity, refrigeration cycling, door-open events, power status,
and equipment vibration. `twin_core/storage_twin.py` consumes these readings
to compute the effective micro-climate each produce twin experiences.

Exposes hooks (`force_door_open`, `force_power_outage`) so that
`iot_simulator/anomaly_injector.py` can trigger scripted fault scenarios
without duplicating simulation logic.
"""

from __future__ import annotations

import asyncio
import csv
import random
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

try:
    from app.iot_simulator.event_bus import event_bus  # type: ignore
except ImportError:
    event_bus = None

try:
    from app.utils.logger import get_logger  # type: ignore
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STORAGE_CONDITIONS_CSV = DATA_DIR / "storage_conditions.csv"

EVENT_TOPIC = "storage.sensor.reading"


# --------------------------------------------------------------------------
# Data models
# --------------------------------------------------------------------------
@dataclass
class StorageUnitProfile:
    storage_id: str
    name: str
    storage_type: str = "cold_storage"  # cold_storage | warehouse | open_shed
    target_temp_c: float = 6.0
    target_humidity_pct: float = 90.0
    has_refrigeration: bool = True
    capacity_units: int = 500


@dataclass
class StorageSensorReading:
    reading_id: str
    storage_id: str
    storage_name: str
    timestamp: str
    ambient_temp_c: float
    ambient_humidity_pct: float
    door_open: bool
    power_status: str  # "on" | "outage"
    refrigeration_active: bool
    vibration_level: float  # 0-10 relative equipment vibration
    occupancy_pct: float

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Profile loading
# --------------------------------------------------------------------------
_DEFAULT_PROFILES: List[StorageUnitProfile] = [
    StorageUnitProfile("cold-a", "Cold Storage A", "cold_storage", 4.0, 90.0, True, 800),
    StorageUnitProfile("warehouse-b", "Warehouse B", "warehouse", 20.0, 60.0, False, 1500),
    StorageUnitProfile("shed-c", "Open Shed C", "open_shed", 28.0, 55.0, False, 400),
]


def load_storage_profiles() -> Dict[str, StorageUnitProfile]:
    profiles: Dict[str, StorageUnitProfile] = {p.storage_id: p for p in _DEFAULT_PROFILES}

    if not STORAGE_CONDITIONS_CSV.exists():
        logger.warning("storage_conditions.csv not found, using default storage profiles")
        return profiles

    try:
        with open(STORAGE_CONDITIONS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    sid = row["storage_id"].strip().lower()
                    profiles[sid] = StorageUnitProfile(
                        storage_id=sid,
                        name=row.get("name", sid.title()),
                        storage_type=row.get("storage_type", "cold_storage"),
                        target_temp_c=float(row.get("target_temp_c", 6.0)),
                        target_humidity_pct=float(row.get("target_humidity_pct", 90.0)),
                        has_refrigeration=str(row.get("has_refrigeration", "true")).lower() == "true",
                        capacity_units=int(float(row.get("capacity_units", 500))),
                    )
                except (KeyError, ValueError) as e:
                    logger.warning(f"Skipping malformed storage row {row}: {e}")
    except Exception as e:
        logger.error(f"Failed to read {STORAGE_CONDITIONS_CSV}: {e}")

    return profiles


# --------------------------------------------------------------------------
# Generator
# --------------------------------------------------------------------------
class StorageSensorGenerator:
    """Simulates a single storage facility's environmental sensor node."""

    def __init__(
        self,
        profile: StorageUnitProfile,
        occupancy_pct: float = 60.0,
        door_open_probability: float = 0.01,
        power_outage_probability: float = 0.001,
        noise_seed: Optional[int] = None,
    ) -> None:
        self.profile = profile
        self.occupancy_pct = occupancy_pct
        self.door_open_probability = door_open_probability
        self.power_outage_probability = power_outage_probability

        self._rng = random.Random(noise_seed)
        self._current_temp_c = profile.target_temp_c
        self._current_humidity_pct = profile.target_humidity_pct
        self._door_open = False
        self._door_open_ticks_remaining = 0
        self._power_status = "on"
        self._power_outage_ticks_remaining = 0
        self._latest: Optional[StorageSensorReading] = None
        self._running = False

    # -- externally triggerable fault hooks (used by anomaly_injector.py) --
    def force_door_open(self, duration_ticks: int = 10) -> None:
        self._door_open = True
        self._door_open_ticks_remaining = duration_ticks
        logger.info(f"[storage_sensor] forced door open on {self.profile.storage_id}")

    def force_power_outage(self, duration_ticks: int = 20) -> None:
        self._power_status = "outage"
        self._power_outage_ticks_remaining = duration_ticks
        logger.info(f"[storage_sensor] forced power outage on {self.profile.storage_id}")

    # -- core simulation step --
    def generate_reading(self) -> StorageSensorReading:
        # Door state: either randomly triggered or still resolving a forced event
        if self._door_open_ticks_remaining > 0:
            self._door_open_ticks_remaining -= 1
            self._door_open = self._door_open_ticks_remaining > 0
        elif self._rng.random() < self.door_open_probability:
            self._door_open = True
            self._door_open_ticks_remaining = self._rng.randint(3, 8)
        else:
            self._door_open = False

        # Power state
        if self._power_outage_ticks_remaining > 0:
            self._power_outage_ticks_remaining -= 1
            self._power_status = "outage" if self._power_outage_ticks_remaining > 0 else "on"
        elif self._rng.random() < self.power_outage_probability:
            self._power_status = "outage"
            self._power_outage_ticks_remaining = self._rng.randint(5, 15)
        else:
            self._power_status = "on"

        refrigeration_active = (
            self.profile.has_refrigeration
            and self._power_status == "on"
            and self._current_temp_c > self.profile.target_temp_c - 0.5
        )

        # Temperature drifts toward target when refrigeration is active,
        # drifts away (toward ambient warmth) when door is open or power is out
        drift = 0.0
        if refrigeration_active:
            drift -= 0.4
        if self._door_open:
            drift += 0.6
        if self._power_status == "outage":
            drift += 0.5
        self._current_temp_c += drift + self._rng.gauss(0, 0.15)
        # gentle pull back toward a plausible ambient ceiling to avoid runaway drift
        self._current_temp_c = max(-5.0, min(self._current_temp_c, 35.0))

        humidity_drift = self._rng.gauss(0, 1.0)
        if self._door_open:
            humidity_drift -= 2.0  # dry outside air enters
        self._current_humidity_pct = max(20.0, min(100.0, self._current_humidity_pct + humidity_drift))

        vibration_level = round(
            max(0.0, self._rng.gauss(2.0 if refrigeration_active else 0.3, 0.5)), 2
        )

        reading = StorageSensorReading(
            reading_id=str(uuid.uuid4()),
            storage_id=self.profile.storage_id,
            storage_name=self.profile.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            ambient_temp_c=round(self._current_temp_c, 2),
            ambient_humidity_pct=round(self._current_humidity_pct, 2),
            door_open=self._door_open,
            power_status=self._power_status,
            refrigeration_active=refrigeration_active,
            vibration_level=vibration_level,
            occupancy_pct=round(self.occupancy_pct, 1),
        )
        self._latest = reading
        return reading

    def latest(self) -> Optional[StorageSensorReading]:
        return self._latest

    async def stream(
        self,
        interval_seconds: float = 5.0,
        on_reading: Optional[Callable[[StorageSensorReading], None]] = None,
    ) -> None:
        self._running = True
        logger.info(f"[storage_sensor] streaming started for storage_id={self.profile.storage_id}")
        while self._running:
            reading = self.generate_reading()
            if event_bus is not None:
                try:
                    await event_bus.publish(EVENT_TOPIC, reading.to_dict())
                except Exception as e:
                    logger.error(f"Failed to publish storage reading: {e}")
            if on_reading:
                on_reading(reading)
            await asyncio.sleep(interval_seconds)

    def stop(self) -> None:
        self._running = False


# --------------------------------------------------------------------------
# Fleet manager
# --------------------------------------------------------------------------
class StorageSensorFleet:
    def __init__(self) -> None:
        self._profiles = load_storage_profiles()
        self._generators: Dict[str, StorageSensorGenerator] = {}
        self._tasks: List[asyncio.Task] = []

    def register(self, storage_key: str, occupancy_pct: float = 60.0) -> StorageSensorGenerator:
        profile = self._profiles.get(storage_key)
        if profile is None:
            raise ValueError(f"Unknown storage unit '{storage_key}'")
        gen = StorageSensorGenerator(profile, occupancy_pct=occupancy_pct)
        self._generators[storage_key] = gen
        return gen

    def get(self, storage_key: str) -> Optional[StorageSensorGenerator]:
        return self._generators.get(storage_key)

    def all_latest(self) -> Dict[str, dict]:
        return {
            sid: gen.latest().to_dict()
            for sid, gen in self._generators.items()
            if gen.latest() is not None
        }

    async def start_all(self, interval_seconds: float = 5.0) -> None:
        for gen in self._generators.values():
            self._tasks.append(asyncio.create_task(gen.stream(interval_seconds)))

    def stop_all(self) -> None:
        for gen in self._generators.values():
            gen.stop()
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()


storage_sensor_fleet = StorageSensorFleet()


if __name__ == "__main__":
    async def _demo():
        fleet = StorageSensorFleet()
        fleet.register("cold-a")
        gen = fleet.get("cold-a")
        gen.force_door_open(duration_ticks=3)
        for _ in range(6):
            print(gen.generate_reading().to_dict())

    asyncio.run(_demo())