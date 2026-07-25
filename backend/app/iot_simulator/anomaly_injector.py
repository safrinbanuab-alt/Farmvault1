"""
anomaly_injector.py
--------------------
Deliberately injects fault scenarios into FarmVault's IoT simulators so the
digital twin, alerting, and dashboard layers have something interesting to
react to (rather than only ever seeing smooth, expected sensor data).

Works on top of the fleets defined in `sensor_generator.py`,
`storage_sensor.py`, and `market_feed.py`, using their public hooks where
available (`force_door_open`, `force_power_outage`, `set_environment`,
`set_trend`) and reverts each effect automatically after a configurable
duration. Every injection publishes a `system.anomaly` event on the shared
`event_bus` so `api/simulation_routes.py`, `services/dashboard_service.py`,
and the websocket layer can surface it as an alert without polling.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from app.iot_simulator.event_bus import event_bus

try:
    from app.utils.logger import get_logger  # type: ignore
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

# Fleet singletons -- degrade gracefully if a sibling module isn't wired up yet.
try:
    from app.iot_simulator.sensor_generator import produce_sensor_fleet  # type: ignore
except ImportError:
    produce_sensor_fleet = None

try:
    from app.iot_simulator.storage_sensor import storage_sensor_fleet  # type: ignore
except ImportError:
    storage_sensor_fleet = None

try:
    from app.iot_simulator.market_feed import market_feed_fleet  # type: ignore
except ImportError:
    market_feed_fleet = None

ANOMALY_EVENT_TOPIC = "system.anomaly"


class AnomalyType(str, Enum):
    STORAGE_DOOR_OPEN = "storage_door_open"
    STORAGE_POWER_OUTAGE = "storage_power_outage"
    STORAGE_TEMPERATURE_SPIKE = "storage_temperature_spike"
    PRODUCE_TEMPERATURE_SHOCK = "produce_temperature_shock"
    PRODUCE_ETHYLENE_LEAK = "produce_ethylene_leak"
    PRODUCE_SENSOR_DROPOUT = "produce_sensor_dropout"
    MARKET_PRICE_SHOCK = "market_price_shock"
    MARKET_CRASH = "market_crash"


class AnomalySeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AnomalyEvent:
    anomaly_id: str
    anomaly_type: str
    severity: str
    target_type: str  # "produce" | "storage" | "market"
    target_id: str
    description: str
    timestamp: str
    duration_seconds: Optional[float] = None
    resolved: bool = False
    metadata: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)


class AnomalyInjector:
    """Orchestrates fault injection across the produce, storage, and market
    simulators, and publishes the results onto the shared event bus."""

    def __init__(
        self,
        produce_fleet=None,
        storage_fleet=None,
        market_fleet=None,
    ) -> None:
        self.produce_fleet = produce_fleet if produce_fleet is not None else produce_sensor_fleet
        self.storage_fleet = storage_fleet if storage_fleet is not None else storage_sensor_fleet
        self.market_fleet = market_fleet if market_fleet is not None else market_feed_fleet

        self._active: Dict[str, AnomalyEvent] = {}
        self._log: List[AnomalyEvent] = []
        self._max_log = 200
        self._chaos_task: Optional[asyncio.Task] = None
        self._chaos_running = False

    # -- internal helpers --
    async def _emit(self, event: AnomalyEvent) -> None:
        self._active[event.anomaly_id] = event
        self._log.append(event)
        if len(self._log) > self._max_log:
            del self._log[: len(self._log) - self._max_log]
        await event_bus.publish(ANOMALY_EVENT_TOPIC, event.to_dict())
        logger.info(f"[anomaly_injector] {event.anomaly_type} on {event.target_type}:{event.target_id} "
                    f"({event.severity})")

    async def _resolve(self, event: AnomalyEvent) -> None:
        event.resolved = True
        self._active.pop(event.anomaly_id, None)
        await event_bus.publish(
            ANOMALY_EVENT_TOPIC,
            {**event.to_dict(), "resolved": True, "description": f"Resolved: {event.description}"},
        )
        logger.info(f"[anomaly_injector] resolved {event.anomaly_type} on "
                    f"{event.target_type}:{event.target_id}")

    def _make_event(
        self,
        anomaly_type: AnomalyType,
        severity: AnomalySeverity,
        target_type: str,
        target_id: str,
        description: str,
        duration_seconds: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> AnomalyEvent:
        return AnomalyEvent(
            anomaly_id=str(uuid.uuid4()),
            anomaly_type=anomaly_type.value,
            severity=severity.value,
            target_type=target_type,
            target_id=target_id,
            description=description,
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_seconds=duration_seconds,
            metadata=metadata or {},
        )

    # -- storage anomalies --
    async def inject_storage_door_open(
        self, storage_id: str, duration_ticks: int = 10, severity: AnomalySeverity = AnomalySeverity.MEDIUM
    ) -> AnomalyEvent:
        if self.storage_fleet is None:
            raise RuntimeError("storage_sensor_fleet is not available")
        gen = self.storage_fleet.get(storage_id)
        if gen is None:
            raise ValueError(f"Unknown storage unit '{storage_id}'")

        gen.force_door_open(duration_ticks=duration_ticks)
        event = self._make_event(
            AnomalyType.STORAGE_DOOR_OPEN, severity, "storage", storage_id,
            f"Door left open on {gen.profile.name}",
            metadata={"duration_ticks": duration_ticks},
        )
        await self._emit(event)
        return event

    async def inject_power_outage(
        self, storage_id: str, duration_ticks: int = 20, severity: AnomalySeverity = AnomalySeverity.HIGH
    ) -> AnomalyEvent:
        if self.storage_fleet is None:
            raise RuntimeError("storage_sensor_fleet is not available")
        gen = self.storage_fleet.get(storage_id)
        if gen is None:
            raise ValueError(f"Unknown storage unit '{storage_id}'")

        gen.force_power_outage(duration_ticks=duration_ticks)
        event = self._make_event(
            AnomalyType.STORAGE_POWER_OUTAGE, severity, "storage", storage_id,
            f"Power outage at {gen.profile.name}",
            metadata={"duration_ticks": duration_ticks},
        )
        await self._emit(event)
        return event

    async def inject_storage_temperature_spike(
        self,
        storage_id: str,
        delta_c: float = 8.0,
        duration_seconds: float = 60.0,
        severity: AnomalySeverity = AnomalySeverity.HIGH,
    ) -> AnomalyEvent:
        if self.storage_fleet is None:
            raise RuntimeError("storage_sensor_fleet is not available")
        gen = self.storage_fleet.get(storage_id)
        if gen is None:
            raise ValueError(f"Unknown storage unit '{storage_id}'")

        gen._current_temp_c += delta_c  # direct nudge; generator will keep drifting naturally afterward
        event = self._make_event(
            AnomalyType.STORAGE_TEMPERATURE_SPIKE, severity, "storage", storage_id,
            f"Sudden +{delta_c:.1f}C temperature spike in {gen.profile.name}",
            duration_seconds=duration_seconds,
            metadata={"delta_c": delta_c},
        )
        await self._emit(event)
        asyncio.create_task(self._auto_resolve(event, duration_seconds))
        return event

    # -- produce anomalies --
    async def inject_produce_temperature_shock(
        self,
        produce_id: str,
        shocked_temp_c: float,
        duration_seconds: float = 60.0,
        severity: AnomalySeverity = AnomalySeverity.MEDIUM,
    ) -> AnomalyEvent:
        if self.produce_fleet is None:
            raise RuntimeError("produce_sensor_fleet is not available")
        gen = self.produce_fleet.get(produce_id)
        if gen is None:
            raise ValueError(f"Unknown produce batch '{produce_id}'")

        original_temp = gen.storage_temp_c
        gen.set_environment(temp_c=shocked_temp_c)
        event = self._make_event(
            AnomalyType.PRODUCE_TEMPERATURE_SHOCK, severity, "produce", produce_id,
            f"{gen.profile.name} batch exposed to {shocked_temp_c:.1f}C",
            duration_seconds=duration_seconds,
            metadata={"original_temp_c": original_temp, "shocked_temp_c": shocked_temp_c},
        )
        await self._emit(event)

        async def _revert():
            await asyncio.sleep(duration_seconds)
            gen.set_environment(temp_c=original_temp)
            await self._resolve(event)

        asyncio.create_task(_revert())
        return event

    async def inject_ethylene_leak(
        self,
        produce_id: str,
        multiplier: float = 3.0,
        duration_seconds: float = 60.0,
        severity: AnomalySeverity = AnomalySeverity.MEDIUM,
    ) -> AnomalyEvent:
        if self.produce_fleet is None:
            raise RuntimeError("produce_sensor_fleet is not available")
        gen = self.produce_fleet.get(produce_id)
        if gen is None:
            raise ValueError(f"Unknown produce batch '{produce_id}'")

        original_rate = gen.profile.base_respiration_rate
        gen.profile.base_respiration_rate = original_rate * multiplier
        event = self._make_event(
            AnomalyType.PRODUCE_ETHYLENE_LEAK, severity, "produce", produce_id,
            f"Nearby ethylene source accelerating ripening of {gen.profile.name}",
            duration_seconds=duration_seconds,
            metadata={"multiplier": multiplier},
        )
        await self._emit(event)
        asyncio.create_task(self._auto_resolve(event, duration_seconds, on_resolve=lambda: setattr(
            gen.profile, "base_respiration_rate", original_rate
        )))
        return event

    async def inject_produce_sensor_dropout(
        self,
        produce_id: str,
        duration_seconds: float = 30.0,
        severity: AnomalySeverity = AnomalySeverity.LOW,
    ) -> AnomalyEvent:
        if self.produce_fleet is None:
            raise RuntimeError("produce_sensor_fleet is not available")
        gen = self.produce_fleet.get(produce_id)
        if gen is None:
            raise ValueError(f"Unknown produce batch '{produce_id}'")

        gen.stop()
        event = self._make_event(
            AnomalyType.PRODUCE_SENSOR_DROPOUT, severity, "produce", produce_id,
            f"Sensor on {gen.profile.name} batch went offline",
            duration_seconds=duration_seconds,
        )
        await self._emit(event)

        async def _revert():
            await asyncio.sleep(duration_seconds)
            asyncio.create_task(gen.stream())
            await self._resolve(event)

        asyncio.create_task(_revert())
        return event

    # -- market anomalies --
    async def inject_market_shock(
        self,
        commodity: str,
        market_name: str,
        drift_pct_per_day: float = 40.0,
        duration_seconds: float = 90.0,
        severity: AnomalySeverity = AnomalySeverity.MEDIUM,
    ) -> AnomalyEvent:
        if self.market_fleet is None:
            raise RuntimeError("market_feed_fleet is not available")
        gen = self.market_fleet.get(commodity, market_name)
        if gen is None:
            raise ValueError(f"No market feed for '{commodity}' at '{market_name}'")

        gen.set_trend(drift_pct_per_day)
        direction = "surge" if drift_pct_per_day > 0 else "crash"
        anomaly_type = AnomalyType.MARKET_CRASH if drift_pct_per_day < 0 else AnomalyType.MARKET_PRICE_SHOCK
        event = self._make_event(
            anomaly_type, severity, "market", f"{commodity}@{market_name}",
            f"Price {direction} for {commodity} at {market_name} ({drift_pct_per_day:+.1f}%/day)",
            duration_seconds=duration_seconds,
            metadata={"drift_pct_per_day": drift_pct_per_day},
        )
        await self._emit(event)
        asyncio.create_task(self._auto_resolve(event, duration_seconds, on_resolve=lambda: gen.set_trend(0.0)))
        return event

    # -- shared auto-resolve helper --
    async def _auto_resolve(self, event: AnomalyEvent, duration_seconds: float, on_resolve=None) -> None:
        await asyncio.sleep(duration_seconds)
        if on_resolve:
            on_resolve()
        await self._resolve(event)

    # -- random / chaos-testing helpers --
    async def inject_random_anomaly(self) -> Optional[AnomalyEvent]:
        """Pick a random registered target and a fitting anomaly type, and inject it."""
        candidates = []

        if self.storage_fleet is not None:
            for storage_id in list(self.storage_fleet._generators.keys()):  # noqa: SLF001
                candidates.append(("storage", storage_id))
        if self.produce_fleet is not None:
            for produce_id in list(self.produce_fleet._generators.keys()):  # noqa: SLF001
                candidates.append(("produce", produce_id))
        if self.market_fleet is not None:
            for commodity, market_name in list(self.market_fleet._generators.keys()):  # noqa: SLF001
                candidates.append(("market", (commodity, market_name)))

        if not candidates:
            logger.warning("[anomaly_injector] no registered sensors/feeds to inject anomalies into")
            return None

        target_type, target_id = random.choice(candidates)

        if target_type == "storage":
            action = random.choice([
                lambda: self.inject_storage_door_open(target_id),
                lambda: self.inject_power_outage(target_id),
                lambda: self.inject_storage_temperature_spike(target_id),
            ])
        elif target_type == "produce":
            action = random.choice([
                lambda: self.inject_produce_temperature_shock(target_id, shocked_temp_c=random.uniform(25, 35)),
                lambda: self.inject_ethylene_leak(target_id),
                lambda: self.inject_produce_sensor_dropout(target_id),
            ])
        else:  # market
            commodity, market_name = target_id
            action = lambda: self.inject_market_shock(
                commodity, market_name, drift_pct_per_day=random.choice([-1, 1]) * random.uniform(15, 50)
            )

        return await action()

    async def run_chaos_loop(self, interval_seconds: float = 60.0, probability: float = 0.3) -> None:
        """Background loop: every `interval_seconds`, roll the dice and maybe
        inject a random anomaly. Intended for long-running demo sessions."""
        self._chaos_running = True
        logger.info("[anomaly_injector] chaos loop started")
        while self._chaos_running:
            await asyncio.sleep(interval_seconds)
            if random.random() < probability:
                try:
                    await self.inject_random_anomaly()
                except Exception as e:
                    logger.error(f"[anomaly_injector] chaos loop injection failed: {e}")

    def start_chaos_loop(self, interval_seconds: float = 60.0, probability: float = 0.3) -> None:
        if self._chaos_task is None or self._chaos_task.done():
            self._chaos_task = asyncio.create_task(self.run_chaos_loop(interval_seconds, probability))

    def stop_chaos_loop(self) -> None:
        self._chaos_running = False
        if self._chaos_task is not None:
            self._chaos_task.cancel()
            self._chaos_task = None

    # -- introspection (used by simulation_routes.py / dashboard_service.py) --
    def active_anomalies(self) -> List[dict]:
        return [e.to_dict() for e in self._active.values()]

    def recent_anomalies(self, limit: int = 50) -> List[dict]:
        return [e.to_dict() for e in self._log[-limit:]]


# Shared singleton bound to the default fleets from the sibling simulator modules.
anomaly_injector = AnomalyInjector()


if __name__ == "__main__":
    async def _demo():
        # Register minimal fleets for a standalone smoke test
        if produce_sensor_fleet is not None:
            produce_sensor_fleet.register("batch-001", "tomato")
        if storage_sensor_fleet is not None:
            storage_sensor_fleet.register("cold-a")
        if market_feed_fleet is not None:
            market_feed_fleet.register("tomato", "Azadpur Mandi")

        injector = AnomalyInjector()

        def log_anomaly(topic: str, payload: dict) -> None:
            print(f"[event] {topic}: {payload.get('description', payload)}")

        event_bus.subscribe(ANOMALY_EVENT_TOPIC, log_anomaly)

        await injector.inject_storage_door_open("cold-a", duration_ticks=3)
        await injector.inject_power_outage("cold-a", duration_ticks=3)
        await injector.inject_market_shock("tomato", "Azadpur Mandi", drift_pct_per_day=-30, duration_seconds=2)
        await asyncio.sleep(2.5)  # let the market shock auto-resolve
        print("recent anomalies:", injector.recent_anomalies())

    asyncio.run(_demo())