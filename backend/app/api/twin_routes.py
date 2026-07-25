"""
twin_routes.py
---------------
The digital-twin control surface: registers produce and storage sensor
twins, starts/stops their live simulation streams, and serves merged
real-time snapshots that combine produce vitals + the storage environment
they sit in + the relevant market price -- exactly what
`frontend/src/components/TwinVisualizer.jsx` needs to render.

Continuous push updates go out over the websocket layer
(`websocket/manager.py`, subscribed to the same `event_bus` topics); this
router is the REST surface for registering twins and pulling point-in-time
snapshots (e.g. on initial page load, or for polling clients).
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
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
from app.iot_simulator.anomaly_injector import anomaly_injector

router = APIRouter(prefix="/api/twin", tags=["Digital Twin"])

_produce_tasks: Dict[str, asyncio.Task] = {}
_storage_tasks: Dict[str, asyncio.Task] = {}

# Lightweight linkage so a produce twin's snapshot can pull in the storage
# environment and market price it's associated with. In a fuller build this
# would live in the database alongside the `patients` record; kept local
# here so this router works standalone against the simulators.
_twin_links: Dict[str, dict] = {}  # produce_id -> {storage_id, commodity, market_name}


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class ProduceTwinRegisterRequest(BaseModel):
    produce_id: str
    catalog_key: str = Field(..., description="e.g. 'tomato'")
    storage_id: Optional[str] = None
    storage_temp_c: Optional[float] = None
    storage_humidity_pct: Optional[float] = None
    commodity: Optional[str] = Field(None, description="Market commodity key for price linkage")
    market_name: Optional[str] = None
    interval_seconds: float = Field(5.0, gt=0)


class StorageTwinRegisterRequest(BaseModel):
    storage_id: str
    catalog_key: str = Field(..., description="e.g. 'cold-a'")
    occupancy_pct: float = Field(60.0, ge=0, le=100)
    interval_seconds: float = Field(5.0, gt=0)


# --------------------------------------------------------------------------
# Produce twins
# --------------------------------------------------------------------------
@router.post("/produce/{produce_id}/register", status_code=201)
async def register_produce_twin(produce_id: str, payload: ProduceTwinRegisterRequest) -> dict:
    existing = _produce_tasks.get(produce_id)
    if existing is not None and not existing.done():
        raise HTTPException(status_code=409, detail=f"Produce twin '{produce_id}' is already running")

    try:
        generator = produce_sensor_fleet.register(
            produce_id,
            payload.catalog_key,
            storage_temp_c=payload.storage_temp_c,
            storage_humidity_pct=payload.storage_humidity_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _produce_tasks[produce_id] = asyncio.create_task(generator.stream(payload.interval_seconds))
    _twin_links[produce_id] = {
        "storage_id": payload.storage_id,
        "commodity": payload.commodity,
        "market_name": payload.market_name,
    }
    logger.info(f"[twin_routes] produce twin '{produce_id}' registered ({payload.catalog_key})")
    return {"produce_id": produce_id, "status": "streaming"}


@router.post("/produce/{produce_id}/stop", status_code=200)
async def stop_produce_twin(produce_id: str) -> None:
    generator = produce_sensor_fleet.get(produce_id)
    if generator is None:
        raise HTTPException(status_code=404, detail=f"No produce twin '{produce_id}'")
    generator.stop()
    task = _produce_tasks.pop(produce_id, None)
    if task is not None:
        task.cancel()


@router.get("/produce")
async def list_produce_twins() -> List[dict]:
    return [
        {"produce_id": pid, **reading}
        for pid, reading in produce_sensor_fleet.all_latest().items()
    ]


@router.get("/produce/{produce_id}/snapshot")
async def get_produce_snapshot(produce_id: str) -> dict:
    generator = produce_sensor_fleet.get(produce_id)
    if generator is None:
        raise HTTPException(status_code=404, detail=f"No produce twin '{produce_id}'")

    latest = generator.latest()
    link = _twin_links.get(produce_id, {})

    storage_snapshot = None
    storage_id = link.get("storage_id")
    if storage_id:
        storage_gen = storage_sensor_fleet.get(storage_id)
        if storage_gen is not None and storage_gen.latest() is not None:
            storage_snapshot = storage_gen.latest().to_dict()

    market_snapshot = None
    commodity, market_name = link.get("commodity"), link.get("market_name")
    if commodity and market_name:
        market_snapshot = market_feed_fleet.get_latest_price(commodity, market_name)

    relevant_anomalies = [
        a for a in anomaly_injector.active_anomalies()
        if a["target_id"] in (produce_id, storage_id)
    ]

    return {
        "produce_id": produce_id,
        "profile": {
            "name": generator.profile.name,
            "category": generator.profile.category,
            "shelf_life_days": generator.profile.shelf_life_days,
        },
        "vitals": latest.to_dict() if latest else None,
        "storage": storage_snapshot,
        "market": market_snapshot,
        "active_anomalies": relevant_anomalies,
    }


# --------------------------------------------------------------------------
# Storage twins
# --------------------------------------------------------------------------
@router.post("/storage/{storage_id}/register", status_code=201)
async def register_storage_twin(storage_id: str, payload: StorageTwinRegisterRequest) -> dict:
    existing = _storage_tasks.get(storage_id)
    if existing is not None and not existing.done():
        raise HTTPException(status_code=409, detail=f"Storage twin '{storage_id}' is already running")

    try:
        generator = storage_sensor_fleet.register(payload.catalog_key, occupancy_pct=payload.occupancy_pct)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _storage_tasks[storage_id] = asyncio.create_task(generator.stream(payload.interval_seconds))
    logger.info(f"[twin_routes] storage twin '{storage_id}' registered ({payload.catalog_key})")
    return {"storage_id": storage_id, "status": "streaming"}


@router.post("/storage/{storage_id}/stop", status_code=200)
async def stop_storage_twin(storage_id: str) -> None:
    generator = storage_sensor_fleet.get(storage_id)
    if generator is None:
        raise HTTPException(status_code=404, detail=f"No storage twin '{storage_id}'")
    generator.stop()
    task = _storage_tasks.pop(storage_id, None)
    if task is not None:
        task.cancel()


@router.get("/storage")
async def list_storage_twins() -> List[dict]:
    return [
        {"storage_id": sid, **reading}
        for sid, reading in storage_sensor_fleet.all_latest().items()
    ]


@router.get("/storage/{storage_id}/snapshot")
async def get_storage_snapshot(storage_id: str) -> dict:
    generator = storage_sensor_fleet.get(storage_id)
    if generator is None:
        raise HTTPException(status_code=404, detail=f"No storage twin '{storage_id}'")

    occupants = [pid for pid, link in _twin_links.items() if link.get("storage_id") == storage_id]
    relevant_anomalies = [
        a for a in anomaly_injector.active_anomalies() if a["target_id"] == storage_id
    ]

    return {
        "storage_id": storage_id,
        "profile": {
            "name": generator.profile.name,
            "storage_type": generator.profile.storage_type,
            "capacity_units": generator.profile.capacity_units,
        },
        "environment": generator.latest().to_dict() if generator.latest() else None,
        "occupant_produce_ids": occupants,
        "active_anomalies": relevant_anomalies,
    }


# --------------------------------------------------------------------------
# Anomalies (cross-twin view)
# --------------------------------------------------------------------------
@router.get("/anomalies/active")
async def get_active_anomalies() -> List[dict]:
    return anomaly_injector.active_anomalies()


@router.get("/anomalies/recent")
async def get_recent_anomalies(limit: int = Query(50, ge=1, le=200)) -> List[dict]:
    return anomaly_injector.recent_anomalies(limit=limit)
