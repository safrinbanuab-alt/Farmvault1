"""
sensor_generator.py
--------------------
Simulates IoT sensors attached to individual produce batches (crates, pallets,
or single-lot shipments) inside FarmVault's digital twin.

Each `ProduceSensorGenerator` models one physical produce twin and emits
periodic `ProduceSensorReading` events (temperature, humidity, ethylene,
CO2, weight loss, firmness, quality score). Readings are published onto the
shared `event_bus` so that `twin_core/produce_twin.py`, the decay model, and
the websocket layer can consume them in real time.

This module has no hard dependency on the rest of the backend being fully
wired up yet -- it degrades gracefully (falls back to stdlib logging / an
in-memory catalog) if `event_bus.py`, `logger.py`, or the CSV data files are
not yet available.
"""

from __future__ import annotations

import asyncio
import csv
import math
import random
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

# --------------------------------------------------------------------------
# Soft dependencies -- fall back cleanly if not yet implemented.
# --------------------------------------------------------------------------
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
PRODUCE_CATALOG_CSV = DATA_DIR / "sample_produce.csv"

EVENT_TOPIC = "produce.sensor.reading"


# --------------------------------------------------------------------------
# Data models
# --------------------------------------------------------------------------
@dataclass
class ProduceProfile:
    """Static reference data describing a produce type's ideal conditions."""

    produce_id: str
    name: str
    category: str = "vegetable"
    ideal_temp_min_c: float = 4.0
    ideal_temp_max_c: float = 10.0
    ideal_humidity_min_pct: float = 85.0
    ideal_humidity_max_pct: float = 95.0
    ethylene_sensitive: bool = True
    base_respiration_rate: float = 1.0  # relative units, higher = decays faster
    shelf_life_days: float = 10.0


@dataclass
class ProduceSensorReading:
    reading_id: str
    produce_id: str
    produce_name: str
    timestamp: str
    temperature_c: float
    humidity_pct: float
    ethylene_ppm: float
    co2_ppm: float
    weight_loss_pct: float
    firmness_index: float  # 100 = fresh, 0 = mushy
    quality_score: float  # 100 = perfect, 0 = spoiled
    elapsed_hours: float

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Catalog loading
# --------------------------------------------------------------------------
_DEFAULT_CATALOG: List[ProduceProfile] = [
    ProduceProfile("tomato", "Tomato", "vegetable", 10, 15, 85, 90, True, 1.4, 14),
    ProduceProfile("onion", "Onion", "vegetable", 0, 4, 65, 75, False, 0.5, 60),
    ProduceProfile("potato", "Potato", "vegetable", 4, 10, 85, 95, False, 0.4, 90),
    ProduceProfile("banana", "Banana", "fruit", 13, 15, 85, 95, True, 1.8, 7),
    ProduceProfile("mango", "Mango", "fruit", 10, 13, 85, 90, True, 1.6, 12),
    ProduceProfile("spinach", "Spinach", "leafy_green", 0, 4, 90, 98, False, 2.2, 5),
]


def load_produce_catalog() -> Dict[str, ProduceProfile]:
    """Load produce reference data from CSV, falling back to built-in defaults
    for any rows that are missing or malformed."""
    catalog: Dict[str, ProduceProfile] = {p.produce_id: p for p in _DEFAULT_CATALOG}

    if not PRODUCE_CATALOG_CSV.exists():
        logger.warning("sample_produce.csv not found, using default produce catalog")
        return catalog

    try:
        with open(PRODUCE_CATALOG_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    pid = row["produce_id"].strip().lower()
                    catalog[pid] = ProduceProfile(
                        produce_id=pid,
                        name=row.get("name", pid.title()),
                        category=row.get("category", "vegetable"),
                        ideal_temp_min_c=float(row.get("ideal_temp_min", 4)),
                        ideal_temp_max_c=float(row.get("ideal_temp_max", 10)),
                        ideal_humidity_min_pct=float(row.get("ideal_humidity_min", 85)),
                        ideal_humidity_max_pct=float(row.get("ideal_humidity_max", 95)),
                        ethylene_sensitive=str(row.get("ethylene_sensitive", "true")).lower() == "true",
                        base_respiration_rate=float(row.get("respiration_rate", 1.0)),
                        shelf_life_days=float(row.get("shelf_life_days", 10)),
                    )
                except (KeyError, ValueError) as e:
                    logger.warning(f"Skipping malformed produce row {row}: {e}")
    except Exception as e:
        logger.error(f"Failed to read {PRODUCE_CATALOG_CSV}: {e}")

    return catalog


# --------------------------------------------------------------------------
# Generator
# --------------------------------------------------------------------------
class ProduceSensorGenerator:
    """Simulates a single physical produce sensor node over time."""

    def __init__(
        self,
        produce_id: str,
        profile: ProduceProfile,
        storage_temp_c: Optional[float] = None,
        storage_humidity_pct: Optional[float] = None,
        noise_seed: Optional[int] = None,
    ) -> None:
        self.produce_id = produce_id
        self.profile = profile
        self.storage_temp_c = storage_temp_c if storage_temp_c is not None else (
            profile.ideal_temp_min_c + profile.ideal_temp_max_c
        ) / 2
        self.storage_humidity_pct = storage_humidity_pct if storage_humidity_pct is not None else (
            profile.ideal_humidity_min_pct + profile.ideal_humidity_max_pct
        ) / 2

        self._rng = random.Random(noise_seed)
        self._start_time = datetime.now(timezone.utc)
        self._elapsed_hours = 0.0
        self._weight_loss_pct = 0.0
        self._quality_score = 100.0
        self._latest: Optional[ProduceSensorReading] = None
        self._running = False

    # -- environment control (called externally e.g. by scenario_engine) --
    def set_environment(self, temp_c: Optional[float] = None, humidity_pct: Optional[float] = None) -> None:
        if temp_c is not None:
            self.storage_temp_c = temp_c
        if humidity_pct is not None:
            self.storage_humidity_pct = humidity_pct

    # -- core simulation step --
    def _temperature_deviation_factor(self) -> float:
        """Returns >1 when storage temp is outside the ideal band (accelerates decay)."""
        lo, hi = self.profile.ideal_temp_min_c, self.profile.ideal_temp_max_c
        if lo <= self.storage_temp_c <= hi:
            return 1.0
        deviation = min(abs(self.storage_temp_c - lo), abs(self.storage_temp_c - hi))
        return 1.0 + (deviation * 0.15)

    def generate_reading(self, dt_hours: float = 1 / 720) -> ProduceSensorReading:
        """Advance the simulation by `dt_hours` (default: one 5-second tick
        expressed in hours) and produce a new sensor reading."""
        self._elapsed_hours += dt_hours

        temp_factor = self._temperature_deviation_factor()

        # Sensor readings with small measurement noise around actual storage conditions
        temperature_c = round(self.storage_temp_c + self._rng.gauss(0, 0.3), 2)
        humidity_pct = round(
            max(0.0, min(100.0, self.storage_humidity_pct + self._rng.gauss(0, 1.5))), 2
        )

        # Ethylene builds up over time for climacteric/ethylene-sensitive produce
        ethylene_base = 0.5 * self.profile.base_respiration_rate * temp_factor
        ethylene_ppm = round(
            max(0.0, ethylene_base * math.log1p(self._elapsed_hours) + self._rng.gauss(0, 0.05)), 3
        ) if self.profile.ethylene_sensitive else round(max(0.0, self._rng.gauss(0.05, 0.02)), 3)

        co2_ppm = round(
            400 + (self.profile.base_respiration_rate * temp_factor * self._elapsed_hours * 2)
            + self._rng.gauss(0, 15),
            1,
        )

        # Weight loss accumulates with respiration + transpiration, worse when too warm/dry
        humidity_deficit = max(0.0, self.profile.ideal_humidity_min_pct - humidity_pct) / 100
        weight_loss_rate = 0.002 * self.profile.base_respiration_rate * temp_factor * (1 + humidity_deficit)
        self._weight_loss_pct = round(self._weight_loss_pct + weight_loss_rate * dt_hours * 24, 3)

        # Quality/firmness decay: exponential decay keyed to shelf life & stress factors
        decay_rate_per_day = (100 / max(self.profile.shelf_life_days, 0.5)) * temp_factor
        self._quality_score = max(0.0, self._quality_score - decay_rate_per_day * (dt_hours / 24))
        firmness_index = max(0.0, round(self._quality_score * self._rng.uniform(0.95, 1.0), 2))

        reading = ProduceSensorReading(
            reading_id=str(uuid.uuid4()),
            produce_id=self.produce_id,
            produce_name=self.profile.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            temperature_c=temperature_c,
            humidity_pct=humidity_pct,
            ethylene_ppm=ethylene_ppm,
            co2_ppm=co2_ppm,
            weight_loss_pct=self._weight_loss_pct,
            firmness_index=firmness_index,
            quality_score=round(self._quality_score, 2),
            elapsed_hours=round(self._elapsed_hours, 3),
        )
        self._latest = reading
        return reading

    def latest(self) -> Optional[ProduceSensorReading]:
        return self._latest

    async def stream(
        self,
        interval_seconds: float = 5.0,
        on_reading: Optional[Callable[[ProduceSensorReading], None]] = None,
    ) -> None:
        """Continuously generate readings and publish them to the event bus."""
        self._running = True
        dt_hours = interval_seconds / 3600
        logger.info(f"[sensor_generator] streaming started for produce_id={self.produce_id}")
        while self._running:
            reading = self.generate_reading(dt_hours=dt_hours)
            if event_bus is not None:
                try:
                    await event_bus.publish(EVENT_TOPIC, reading.to_dict())
                except Exception as e:
                    logger.error(f"Failed to publish produce reading: {e}")
            if on_reading:
                on_reading(reading)
            await asyncio.sleep(interval_seconds)

    def stop(self) -> None:
        self._running = False


# --------------------------------------------------------------------------
# Fleet manager -- convenience wrapper for running many produce twins at once
# --------------------------------------------------------------------------
class ProduceSensorFleet:
    def __init__(self) -> None:
        self._catalog = load_produce_catalog()
        self._generators: Dict[str, ProduceSensorGenerator] = {}
        self._tasks: List[asyncio.Task] = []

    def register(
        self,
        produce_id: str,
        catalog_key: str,
        storage_temp_c: Optional[float] = None,
        storage_humidity_pct: Optional[float] = None,
    ) -> ProduceSensorGenerator:
        profile = self._catalog.get(catalog_key)
        if profile is None:
            raise ValueError(f"Unknown produce type '{catalog_key}' in catalog")
        gen = ProduceSensorGenerator(produce_id, profile, storage_temp_c, storage_humidity_pct)
        self._generators[produce_id] = gen
        return gen

    def get(self, produce_id: str) -> Optional[ProduceSensorGenerator]:
        return self._generators.get(produce_id)

    def all_latest(self) -> Dict[str, dict]:
        return {
            pid: gen.latest().to_dict()
            for pid, gen in self._generators.items()
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


# Shared singleton used by the rest of the app (routes, twin_core, etc.)
produce_sensor_fleet = ProduceSensorFleet()


if __name__ == "__main__":
    # Quick standalone smoke test
    async def _demo():
        fleet = ProduceSensorFleet()
        fleet.register("batch-001", "tomato", storage_temp_c=18.0)
        gen = fleet.get("batch-001")
        for _ in range(5):
            r = gen.generate_reading(dt_hours=1.0)
            print(r.to_dict())

    asyncio.run(_demo())