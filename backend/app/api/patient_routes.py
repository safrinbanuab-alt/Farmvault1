"""
patient_routes.py
------------------
CRUD + admission/monitoring routes for produce batches.

FarmVault treats each produce batch as a "patient" under continuous digital-
twin observation -- the same way a hospital monitors a patient's vitals, a
crate of tomatoes gets its temperature, humidity, ethylene, and quality
score tracked in real time. This router owns the *business record* for a
batch (who grew it, how much, its current status); the live sensor stream
itself is driven by `iot_simulator/sensor_generator.py`.

"Admitting" a patient links a produce batch to a running sensor twin.
"Discharging" a patient stops that stream (e.g. the batch was sold or
disposed of).

Persistence: this router is written against `services/produce_service.py`
if it's available, and otherwise falls back to a simple in-memory store so
the API is testable/runnable before the persistence layer exists.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from app.utils.logger import get_logger  # type: ignore
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

from app.iot_simulator.event_bus import event_bus
from app.iot_simulator.sensor_generator import produce_sensor_fleet, load_produce_catalog

# Optional persistence-layer service -- falls back to an in-memory store below
# if `services/produce_service.py` doesn't exist yet.
try:
    from app.services import produce_service  # type: ignore
except ImportError:
    produce_service = None

router = APIRouter(
    prefix="/patients",
    tags=["Produce Batches"]
)

PRODUCE_READING_TOPIC = "produce.sensor.reading"
VALID_STATUSES = {"registered", "monitoring", "discharged"}


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
from typing import Literal

class ProduceBatchCreate(BaseModel):
    produce_type: Literal[
        "banana",
        "mango",
        "onion",
        "potato",
        "spinach",
        "tomato"
    ] = Field(
        ...,
        description="Catalog key, e.g. 'tomato', 'onion'"
    )

    batch_code: Optional[str] = Field(
        None,
        description="Human-readable lot/batch code"
    )

    quantity_kg: float = Field(..., gt=0)
    origin_farm: Optional[str] = None
    notes: Optional[str] = None
class ProduceBatchUpdate(BaseModel):
    quantity_kg: Optional[float] = Field(None, gt=0)
    origin_farm: Optional[str] = None
    notes: Optional[str] = None


class AdmitRequest(BaseModel):
    storage_id: Optional[str] = Field(None, description="Storage unit this batch is placed in")
    storage_temp_c: Optional[float] = None
    storage_humidity_pct: Optional[float] = None
    interval_seconds: float = Field(5.0, gt=0, description="Sensor sampling interval")


class DischargeRequest(BaseModel):
    reason: str = Field("sold", description="e.g. 'sold', 'disposed', 'transferred'")


class ProduceBatchOut(ProduceBatchCreate):
    patient_id: str
    status: str
    storage_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# In-memory fallback store (used only if services/produce_service.py is absent)
# --------------------------------------------------------------------------
_patients_db: Dict[str, dict] = {}
_stream_tasks: Dict[str, asyncio.Task] = {}
_vitals_history: Dict[str, Deque[dict]] = defaultdict(lambda: deque(maxlen=200))


def _on_produce_reading(topic: str, payload: dict) -> None:
    produce_id = payload.get("produce_id")
    if produce_id:
        _vitals_history[produce_id].append(payload)


event_bus.subscribe(PRODUCE_READING_TOPIC, _on_produce_reading)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_patient_or_404(patient_id: str) -> dict:
    if produce_service is not None:
        record = produce_service.get_produce_batch(patient_id)
    else:
        record = _patients_db.get(patient_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Patient '{patient_id}' not found")
    return record


# --------------------------------------------------------------------------
# CRUD routes
# --------------------------------------------------------------------------
@router.post("", response_model=ProduceBatchOut, status_code=201)
async def create_patient(payload: ProduceBatchCreate) -> ProduceBatchOut:
    catalog = load_produce_catalog()
    if payload.produce_type.lower() not in catalog:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown produce_type '{payload.produce_type}'. "
                   f"Known types: {sorted(catalog.keys())}",
        )

    patient_id = str(uuid.uuid4())
    record = {
        "patient_id": patient_id,
        **payload.model_dump(),
        "status": "registered",
        "storage_id": None,
        "created_at": _now(),
        "updated_at": _now(),
    }

    if produce_service is not None:
        produce_service.create_produce_batch(record)
    else:
        _patients_db[patient_id] = record

    logger.info(f"[patient_routes] registered patient {patient_id} ({payload.produce_type})")
    return ProduceBatchOut(**record)


@router.get("", response_model=List[ProduceBatchOut])
async def list_patients(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[ProduceBatchOut]:
    if produce_service is not None:
        records = produce_service.list_produce_batches(status=status, limit=limit, offset=offset)
    else:
        records = list(_patients_db.values())
        if status:
            records = [r for r in records if r["status"] == status]
        records = records[offset: offset + limit]
    return [ProduceBatchOut(**r) for r in records]


@router.get("/{patient_id}", response_model=ProduceBatchOut)
async def get_patient(patient_id: str) -> ProduceBatchOut:
    return ProduceBatchOut(**_get_patient_or_404(patient_id))


@router.put("/{patient_id}", response_model=ProduceBatchOut)
async def update_patient(patient_id: str, payload: ProduceBatchUpdate) -> ProduceBatchOut:
    record = _get_patient_or_404(patient_id)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    record.update(updates)
    record["updated_at"] = _now()

    if produce_service is not None:
        produce_service.update_produce_batch(patient_id, updates)
    return ProduceBatchOut(**record)


@router.delete("/{patient_id}", status_code=200)
async def delete_patient(patient_id: str) -> None:
    _get_patient_or_404(patient_id)  # 404s if missing

    task = _stream_tasks.pop(patient_id, None)
    if task is not None:
        task.cancel()

    if produce_service is not None:
        produce_service.delete_produce_batch(patient_id)
    else:
        _patients_db.pop(patient_id, None)
    _vitals_history.pop(patient_id, None)


# --------------------------------------------------------------------------
# Admission / discharge (wires the record to the live sensor twin)
# --------------------------------------------------------------------------
@router.post("/{patient_id}/admit", response_model=ProduceBatchOut)
async def admit_patient(patient_id: str, payload: AdmitRequest) -> ProduceBatchOut:
    record = _get_patient_or_404(patient_id)

    existing_task = _stream_tasks.get(patient_id)
    if existing_task is not None and not existing_task.done():
        raise HTTPException(status_code=409, detail=f"Patient '{patient_id}' is already being monitored")

    catalog_key = record["produce_type"].lower()
    try:
        generator = produce_sensor_fleet.register(
            patient_id,
            catalog_key,
            storage_temp_c=payload.storage_temp_c,
            storage_humidity_pct=payload.storage_humidity_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _stream_tasks[patient_id] = asyncio.create_task(generator.stream(payload.interval_seconds))

    record["status"] = "monitoring"
    record["storage_id"] = payload.storage_id
    record["updated_at"] = _now()
    if produce_service is not None:
        produce_service.update_produce_batch(patient_id, record)

    logger.info(f"[patient_routes] admitted patient {patient_id} into storage {payload.storage_id}")
    return ProduceBatchOut(**record)


@router.post("/{patient_id}/discharge", response_model=ProduceBatchOut)
async def discharge_patient(patient_id: str, payload: DischargeRequest) -> ProduceBatchOut:
    record = _get_patient_or_404(patient_id)

    generator = produce_sensor_fleet.get(patient_id)
    if generator is not None:
        generator.stop()
    task = _stream_tasks.pop(patient_id, None)
    if task is not None:
        task.cancel()

    record["status"] = "discharged"
    record["updated_at"] = _now()
    record["notes"] = f"{record.get('notes') or ''} [discharged: {payload.reason}]".strip()
    if produce_service is not None:
        produce_service.update_produce_batch(patient_id, record)

    logger.info(f"[patient_routes] discharged patient {patient_id} ({payload.reason})")
    return ProduceBatchOut(**record)


# --------------------------------------------------------------------------
# Vitals (live sensor twin data)
# --------------------------------------------------------------------------
@router.get("/{patient_id}/vitals")
async def get_vitals(patient_id: str) -> dict:
    _get_patient_or_404(patient_id)
    generator = produce_sensor_fleet.get(patient_id)
    if generator is None or generator.latest() is None:
        raise HTTPException(status_code=404, detail="No vitals recorded yet -- has this patient been admitted?")
    return generator.latest().to_dict()


@router.get("/{patient_id}/vitals/history")
async def get_vitals_history(patient_id: str, limit: int = Query(50, ge=1, le=200)) -> List[dict]:
    _get_patient_or_404(patient_id)
    return list(_vitals_history.get(patient_id, []))[-limit:]


@router.get("/{patient_id}/health-score")
async def get_health_score(patient_id: str) -> dict:
    _get_patient_or_404(patient_id)
    generator = produce_sensor_fleet.get(patient_id)
    if generator is None or generator.latest() is None:
        raise HTTPException(status_code=404, detail="No vitals recorded yet -- has this patient been admitted?")

    reading = generator.latest()
    score = reading.quality_score
    if score >= 90:
        label = "excellent"
    elif score >= 75:
        label = "good"
    elif score >= 50:
        label = "fair"
    elif score >= 25:
        label = "poor"
    else:
        label = "critical"

    return {
        "patient_id": patient_id,
        "quality_score": score,
        "label": label,
        "firmness_index": reading.firmness_index,
        "weight_loss_pct": reading.weight_loss_pct,
        "as_of": reading.timestamp,
    }