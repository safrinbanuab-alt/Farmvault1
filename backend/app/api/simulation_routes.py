"""
simulation_routes.py
---------------------
Global simulation controls for FarmVault's digital twin -- the "control
room" endpoints behind `frontend/src/pages/ScenarioAnalysis.jsx` and the
`InjectAnomalyButton.jsx` component. Handles bulk start/stop of every
registered produce/storage/market stream, chaos-mode toggling, and direct,
type-specific anomaly injection (door open, power outage, temperature
shock, ethylene leak, sensor dropout, market shock).

For scripted what-if scenarios (e.g. "simulate a 3-day heatwave"), this
router defers to `twin_core/scenario_engine.py` when it's available and
falls back to a simple sequence of direct anomaly injections otherwise.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from app.utils.logger import get_logger  # type: ignore
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

from app.iot_simulator.sensor_generator import produce_sensor_fleet
from app.iot_simulator.storage_sensor import storage_sensor_fleet
from app.iot_simulator.market_feed import market_feed_fleet
from app.iot_simulator.anomaly_injector import anomaly_injector, AnomalySeverity
from app.iot_simulator.event_bus import event_bus

try:
    from app.twin_core import scenario_engine  # type: ignore
except ImportError:
    scenario_engine = None

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class StartRequest(BaseModel):
    produce_interval_seconds: float = Field(5.0, gt=0)
    storage_interval_seconds: float = Field(5.0, gt=0)
    market_interval_seconds: float = Field(10.0, gt=0)


class ChaosConfig(BaseModel):
    interval_seconds: float = Field(60.0, gt=0)
    probability: float = Field(0.3, ge=0.0, le=1.0)


class AnomalyInjectRequest(BaseModel):
    anomaly_type: str = Field(
        ...,
        description="One of: storage_door_open, storage_power_outage, storage_temperature_spike, "
                    "produce_temperature_shock, produce_ethylene_leak, produce_sensor_dropout, "
                    "market_price_shock",
    )
    target_id: str = Field(..., description="storage_id, produce_id, or 'commodity@market_name'")
    severity: str = Field("medium", description="low | medium | high | critical")
    duration_seconds: float = Field(60.0, gt=0)
    magnitude: Optional[float] = Field(
        None, description="delta_c / multiplier / drift_pct_per_day, depending on anomaly_type"
    )


class ScenarioRequest(BaseModel):
    name: str = Field(..., description="e.g. 'heatwave', 'power_grid_failure', 'market_glut'")
    target_ids: List[str] = Field(default_factory=list)
    duration_seconds: float = Field(300.0, gt=0)
    intensity: float = Field(1.0, gt=0, description="Multiplier on the scenario's default severity")


# --------------------------------------------------------------------------
# Bulk start/stop
# --------------------------------------------------------------------------
@router.post("/start")
async def start_simulation(payload: StartRequest) -> dict:
    await produce_sensor_fleet.start_all(payload.produce_interval_seconds)
    await storage_sensor_fleet.start_all(payload.storage_interval_seconds)
    await market_feed_fleet.start_all(payload.market_interval_seconds)
    logger.info("[simulation_routes] started all registered twins/feeds")
    return {
        "status": "started",
        "produce_twins": len(produce_sensor_fleet._generators),  # noqa: SLF001
        "storage_twins": len(storage_sensor_fleet._generators),  # noqa: SLF001
        "market_feeds": len(market_feed_fleet._generators),  # noqa: SLF001
    }


@router.post("/stop")
async def stop_simulation() -> dict:
    produce_sensor_fleet.stop_all()
    storage_sensor_fleet.stop_all()
    market_feed_fleet.stop_all()
    anomaly_injector.stop_chaos_loop()
    logger.info("[simulation_routes] stopped all registered twins/feeds")
    return {"status": "stopped"}


@router.get("/status")
async def simulation_status() -> dict:
    return {
        "produce_twins": len(produce_sensor_fleet._generators),  # noqa: SLF001
        "storage_twins": len(storage_sensor_fleet._generators),  # noqa: SLF001
        "market_feeds": len(market_feed_fleet._generators),  # noqa: SLF001
        "active_anomalies": len(anomaly_injector.active_anomalies()),
        "chaos_mode_running": anomaly_injector._chaos_running,  # noqa: SLF001
        "event_bus": event_bus.stats(),
    }


# --------------------------------------------------------------------------
# Chaos mode
# --------------------------------------------------------------------------
@router.post("/chaos/start")
async def start_chaos(payload: ChaosConfig) -> dict:
    anomaly_injector.start_chaos_loop(payload.interval_seconds, payload.probability)
    return {
        "status": "chaos_mode_started",
        "interval_seconds": payload.interval_seconds,
        "probability": payload.probability,
    }


@router.post("/chaos/stop")
async def stop_chaos() -> dict:
    anomaly_injector.stop_chaos_loop()
    return {"status": "chaos_mode_stopped"}


# --------------------------------------------------------------------------
# Direct anomaly injection
# --------------------------------------------------------------------------
_ANOMALY_DISPATCH = {
    "storage_door_open": lambda target_id, sev, dur, mag: anomaly_injector.inject_storage_door_open(
        target_id, duration_ticks=int(mag) if mag else 10, severity=sev
    ),
    "storage_power_outage": lambda target_id, sev, dur, mag: anomaly_injector.inject_power_outage(
        target_id, duration_ticks=int(mag) if mag else 20, severity=sev
    ),
    "storage_temperature_spike": lambda target_id, sev, dur, mag: anomaly_injector.inject_storage_temperature_spike(
        target_id, delta_c=mag if mag is not None else 8.0, duration_seconds=dur, severity=sev
    ),
    "produce_temperature_shock": lambda target_id, sev, dur, mag: anomaly_injector.inject_produce_temperature_shock(
        target_id, shocked_temp_c=mag if mag is not None else 30.0, duration_seconds=dur, severity=sev
    ),
    "produce_ethylene_leak": lambda target_id, sev, dur, mag: anomaly_injector.inject_ethylene_leak(
        target_id, multiplier=mag if mag is not None else 3.0, duration_seconds=dur, severity=sev
    ),
    "produce_sensor_dropout": lambda target_id, sev, dur, mag: anomaly_injector.inject_produce_sensor_dropout(
        target_id, duration_seconds=dur, severity=sev
    ),
}


@router.post("/anomalies/inject")
async def inject_anomaly(payload: AnomalyInjectRequest) -> dict:
    try:
        severity = AnomalySeverity(payload.severity.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid severity '{payload.severity}'")

    if payload.anomaly_type == "market_price_shock":
        if "@" not in payload.target_id:
            raise HTTPException(status_code=400, detail="target_id for market anomalies must be 'commodity@market_name'")
        commodity, market_name = payload.target_id.split("@", 1)
        try:
            event = await anomaly_injector.inject_market_shock(
                commodity, market_name,
                drift_pct_per_day=payload.magnitude if payload.magnitude is not None else 40.0,
                duration_seconds=payload.duration_seconds,
                severity=severity,
            )
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return event.to_dict()

    action = _ANOMALY_DISPATCH.get(payload.anomaly_type)
    if action is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown anomaly_type '{payload.anomaly_type}'. Valid types: "
                   f"{sorted(list(_ANOMALY_DISPATCH.keys()) + ['market_price_shock'])}",
        )

    try:
        event = await action(payload.target_id, severity, payload.duration_seconds, payload.magnitude)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return event.to_dict()


@router.post("/anomalies/random")
async def inject_random() -> dict:
    event = await anomaly_injector.inject_random_anomaly()
    if event is None:
        raise HTTPException(status_code=400, detail="No registered twins/feeds available to inject an anomaly into")
    return event.to_dict()


# --------------------------------------------------------------------------
# Scripted scenarios
# --------------------------------------------------------------------------
@router.post("/scenarios/run")
async def run_scenario(payload: ScenarioRequest) -> dict:
    if scenario_engine is not None:
        result = await scenario_engine.run(payload.name, payload.target_ids, payload.duration_seconds, payload.intensity)
        return result

    # Fallback: map a few well-known scenario names onto direct anomaly injections
    # so the frontend has something to demo against before scenario_engine.py exists.
    injected = []
    if payload.name == "heatwave":
        for target_id in payload.target_ids:
            gen = storage_sensor_fleet.get(target_id)
            if gen is not None:
                event = await anomaly_injector.inject_storage_temperature_spike(
                    target_id, delta_c=6.0 * payload.intensity, duration_seconds=payload.duration_seconds
                )
                injected.append(event.to_dict())
    elif payload.name == "power_grid_failure":
        for target_id in payload.target_ids:
            event = await anomaly_injector.inject_power_outage(
                target_id, duration_ticks=int(20 * payload.intensity)
            )
            injected.append(event.to_dict())
    elif payload.name == "market_glut":
        for target_id in payload.target_ids:
            if "@" not in target_id:
                continue
            commodity, market_name = target_id.split("@", 1)
            event = await anomaly_injector.inject_market_shock(
                commodity, market_name,
                drift_pct_per_day=-30.0 * payload.intensity,
                duration_seconds=payload.duration_seconds,
            )
            injected.append(event.to_dict())
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{payload.name}' and scenario_engine.py is not available. "
                   f"Known fallback scenarios: heatwave, power_grid_failure, market_glut",
        )

    return {
        "scenario": payload.name,
        "engine": "fallback-direct-injection",
        "events": injected,
    }