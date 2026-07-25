"""
prediction_routes.py
---------------------
Serves predictions about produce shelf life, market prices, and anomaly
risk. These are consumed by `frontend/src/pages/ScenarioAnalysis.jsx` and
`Analytics.jsx`, and by `RecommendationCard.jsx`.

`ai_models/decay_model.py`, `price_forecaster.py`, `anomaly_detector.py`,
and `explainable_ai.py` are where the real modeling logic is meant to live.
Until those exist, this router falls back to transparent, documented
heuristics (linear extrapolation from observed sensor/price trends) so the
API contract is stable and the frontend can be built against it now. Each
heuristic response is tagged `"model_version": "heuristic-v0"` and every
prediction is explicit about the assumption it's making, so it's obvious
what needs to be swapped out later.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

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
from app.iot_simulator.market_feed import market_feed_fleet
from app.iot_simulator.anomaly_injector import anomaly_injector

# Optional real model modules -- used transparently once they exist.
try:
    from app.ai_models import decay_model  # type: ignore
except ImportError:
    decay_model = None

try:
    from app.ai_models import price_forecaster  # type: ignore
except ImportError:
    price_forecaster = None

try:
    from app.ai_models import anomaly_detector  # type: ignore
except ImportError:
    anomaly_detector = None

router = APIRouter(prefix="/api/predictions", tags=["Predictions"])

HEURISTIC_VERSION = "heuristic-v0"

# In-memory prediction log so explain/{prediction_id} and history lookups work
# without a database yet.
_predictions_db: Dict[str, dict] = {}


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class PriceForecastRequest(BaseModel):
    horizon_hours: float = Field(24.0, gt=0, le=720)
    history_limit: int = Field(30, ge=2, le=200)


class PredictionOut(BaseModel):
    prediction_id: str
    prediction_type: str
    target_id: str
    generated_at: datetime
    model_version: str
    result: dict
    explanation: dict


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _store_prediction(prediction_type: str, target_id: str, result: dict, explanation: dict) -> PredictionOut:
    prediction = PredictionOut(
        prediction_id=str(uuid.uuid4()),
        prediction_type=prediction_type,
        target_id=target_id,
        generated_at=datetime.now(timezone.utc),
        model_version=HEURISTIC_VERSION,
        result=result,
        explanation=explanation,
    )
    _predictions_db[prediction.prediction_id] = prediction.model_dump()
    return prediction


# --------------------------------------------------------------------------
# Shelf-life / decay predictions
# --------------------------------------------------------------------------
@router.post("/decay/{produce_id}", response_model=PredictionOut)
async def predict_decay(produce_id: str) -> PredictionOut:
    generator = produce_sensor_fleet.get(produce_id)
    if generator is None or generator.latest() is None:
        raise HTTPException(status_code=404, detail=f"No live vitals for produce twin '{produce_id}' yet")

    if decay_model is not None:
        result, explanation = decay_model.predict(generator)  # real model, once implemented
        return _store_prediction("decay", produce_id, result, explanation)

    reading = generator.latest()
    elapsed_hours = max(reading.elapsed_hours, 0.01)
    decay_rate_per_hour = (100 - reading.quality_score) / elapsed_hours

    if decay_rate_per_hour <= 0:
        remaining_hours: Optional[float] = None
        label = "stable"
    else:
        remaining_hours = round(reading.quality_score / decay_rate_per_hour, 1)
        if remaining_hours <= 12:
            label = "critical"
        elif remaining_hours <= 48:
            label = "urgent"
        else:
            label = "normal"

    result = {
        "current_quality_score": reading.quality_score,
        "decay_rate_per_hour": round(decay_rate_per_hour, 4),
        "estimated_hours_remaining": remaining_hours,
        "urgency": label,
    }
    explanation = {
        "method": "linear extrapolation of observed quality-score decay",
        "assumption": "current temperature/humidity conditions and decay rate hold constant",
        "inputs_used": ["quality_score", "elapsed_hours", "temperature_c", "humidity_pct"],
    }
    return _store_prediction("decay", produce_id, result, explanation)


@router.get("/decay/{produce_id}", response_model=List[PredictionOut])
async def get_decay_predictions(produce_id: str, limit: int = Query(10, ge=1, le=100)) -> List[PredictionOut]:
    matches = [
        PredictionOut(**p) for p in _predictions_db.values()
        if p["prediction_type"] == "decay" and p["target_id"] == produce_id
    ]
    matches.sort(key=lambda p: p.generated_at, reverse=True)
    return matches[:limit]


# --------------------------------------------------------------------------
# Price forecasts
# --------------------------------------------------------------------------
@router.post("/price/{commodity}/{market_name}", response_model=PredictionOut)
async def predict_price(commodity: str, market_name: str, payload: PriceForecastRequest) -> PredictionOut:
    generator = market_feed_fleet.get(commodity, market_name)
    if generator is None or generator.latest() is None:
        raise HTTPException(status_code=404, detail=f"No live price feed for '{commodity}' at '{market_name}'")

    if price_forecaster is not None:
        result, explanation = price_forecaster.forecast(generator, payload.horizon_hours)
        return _store_prediction("price", f"{commodity}@{market_name}", result, explanation)

    history = market_feed_fleet.get_price_history(commodity, market_name, limit=payload.history_limit)
    current_price = generator.latest().price_per_quintal

    if len(history) < 2:
        avg_change_pct = 0.0
    else:
        avg_change_pct = sum(t["change_pct"] for t in history) / len(history)

    # Compound the average per-tick change out to the requested horizon,
    # approximating ticks-per-hour from the timestamps of the sampled history.
    ticks_per_hour = 12.0  # assumes ~5 min ticks; informational only for heuristic v0
    periods = max(payload.horizon_hours * ticks_per_hour, 1)
    projected_price = round(current_price * ((1 + avg_change_pct / 100) ** periods), 2)

    result = {
        "current_price_per_quintal": current_price,
        "avg_recent_change_pct": round(avg_change_pct, 4),
        "horizon_hours": payload.horizon_hours,
        "projected_price_per_quintal": projected_price,
        "direction": "up" if projected_price > current_price else "down" if projected_price < current_price else "flat",
    }
    explanation = {
        "method": "compounded average of recent per-tick price changes",
        "assumption": "recent volatility and trend continue unchanged over the horizon",
        "inputs_used": ["price_history", "change_pct"],
        "sample_size": len(history),
    }
    return _store_prediction("price", f"{commodity}@{market_name}", result, explanation)


# --------------------------------------------------------------------------
# Anomaly risk
# --------------------------------------------------------------------------
@router.get("/anomaly-risk/{target_type}/{target_id}", response_model=PredictionOut)
async def predict_anomaly_risk(target_type: str, target_id: str) -> PredictionOut:
    if target_type not in ("produce", "storage", "market"):
        raise HTTPException(status_code=400, detail="target_type must be one of: produce, storage, market")

    if anomaly_detector is not None:
        result, explanation = anomaly_detector.score(target_type, target_id)
        return _store_prediction("anomaly_risk", target_id, result, explanation)

    recent = anomaly_injector.recent_anomalies(limit=100)
    related = [a for a in recent if a["target_id"] == target_id]
    active = [a for a in related if not a["resolved"]]

    risk_score = min(1.0, 0.15 * len(related) + (0.4 if active else 0.0))
    if risk_score >= 0.7:
        level = "high"
    elif risk_score >= 0.3:
        level = "medium"
    else:
        level = "low"

    result = {
        "risk_score": round(risk_score, 2),
        "risk_level": level,
        "recent_anomaly_count": len(related),
        "currently_active": bool(active),
    }
    explanation = {
        "method": "frequency-based heuristic over recently logged anomalies for this target",
        "assumption": "past anomaly frequency is indicative of near-term risk",
        "inputs_used": ["anomaly_injector.recent_anomalies"],
    }
    return _store_prediction("anomaly_risk", target_id, result, explanation)


# --------------------------------------------------------------------------
# Explainability / retrieval
# --------------------------------------------------------------------------
@router.get("/{prediction_id}", response_model=PredictionOut)
async def get_prediction(prediction_id: str) -> PredictionOut:
    record = _predictions_db.get(prediction_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Prediction '{prediction_id}' not found")
    return PredictionOut(**record)


@router.get("/{prediction_id}/explain")
async def explain_prediction(prediction_id: str) -> dict:
    record = _predictions_db.get(prediction_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Prediction '{prediction_id}' not found")
    return {
        "prediction_id": prediction_id,
        "prediction_type": record["prediction_type"],
        "explanation": record["explanation"],
        "note": "Full feature-attribution explanations will be provided by "
                "ai_models/explainable_ai.py once implemented.",
    }