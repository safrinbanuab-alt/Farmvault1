"""
Twin schemas.

Composite Pydantic models that stitch together Produce, Storage, Market, and
Prediction data into the "digital twin" views consumed by
twin_core/produce_twin.py, twin_core/scenario_engine.py, api/twin_routes.py,
api/simulation_routes.py, and streamed to the frontend over the websocket
(TwinVisualizer.jsx, ScenarioComparator.jsx, Timeline.jsx).
"""

from datetime import datetime
from typing import Optional, Literal, Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.produce import ProduceStage, QualityGrade
from app.models.alert import AlertType, AlertSeverity
from app.schemas.produce_schema import ProduceResponse
from app.schemas.prediction_schema import PredictionResponse
from app.schemas.market_schema import ProduceMarketComparison


# ---------------------------------------------------------------------------
# Nested lightweight summaries (kept local since storage_schema.py doesn't
# exist as a standalone file in this project)
# ---------------------------------------------------------------------------

class StorageSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    storage_type: str
    capacity_kg: float
    current_load_kg: float
    current_temperature_c: Optional[float] = None
    current_humidity_pct: Optional[float] = None
    ideal_temp_min_c: Optional[float] = None
    ideal_temp_max_c: Optional[float] = None
    ideal_humidity_min_pct: Optional[float] = None
    ideal_humidity_max_pct: Optional[float] = None


class AlertSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    is_resolved: bool
    triggered_at: datetime


# ---------------------------------------------------------------------------
# Composite twin state
# ---------------------------------------------------------------------------

class TwinState(BaseModel):
    """
    The full snapshot of a Produce batch's digital twin at a point in time:
    its own attributes, the storage environment it sits in, the latest AI
    predictions, active alerts, and how it stacks up against the market.
    """

    produce: ProduceResponse
    storage: Optional[StorageSnapshot] = None

    latest_decay_prediction: Optional[PredictionResponse] = None
    latest_price_prediction: Optional[PredictionResponse] = None
    latest_anomaly_prediction: Optional[PredictionResponse] = None

    active_alerts: list[AlertSummary] = Field(default_factory=list)
    market_comparison: Optional[ProduceMarketComparison] = None

    health_score: Optional[float] = Field(
        None, ge=0, le=100, description="Composite 0-100 twin health indicator"
    )
    as_of: datetime


# ---------------------------------------------------------------------------
# Timeline (Timeline.jsx)
# ---------------------------------------------------------------------------

class TwinTimelineEvent(BaseModel):
    timestamp: datetime
    event_type: Literal[
        "harvested",
        "stage_change",
        "storage_moved",
        "alert_raised",
        "alert_resolved",
        "prediction_generated",
        "sold",
        "disposed",
        "anomaly_injected",
    ]
    description: str
    metadata: Optional[dict[str, Any]] = None


class TwinTimelineResponse(BaseModel):
    produce_id: str
    events: list[TwinTimelineEvent]


# ---------------------------------------------------------------------------
# Scenario / "what-if" simulation (scenario_engine.py + ScenarioComparator.jsx)
# ---------------------------------------------------------------------------

class ScenarioParameters(BaseModel):
    """Inputs a user can tweak to simulate an alternate future for a batch."""

    target_storage_type: Optional[str] = None
    temperature_override_c: Optional[float] = None
    humidity_override_pct: Optional[float] = None
    days_to_simulate: float = Field(7, ge=1, le=90)
    sell_on_day: Optional[float] = Field(None, ge=0)
    apply_discount_pct: Optional[float] = Field(None, ge=0, le=100)


class ScenarioRequest(BaseModel):
    produce_id: str
    scenario_name: str = Field(..., max_length=100, examples=["Move to cold storage"])
    parameters: ScenarioParameters


class ScenarioProjectedPoint(BaseModel):
    day: float
    projected_decay_percent: float
    projected_quality_grade: Optional[QualityGrade] = None
    projected_stage: Optional[ProduceStage] = None
    projected_price_per_kg: Optional[float] = None
    projected_value: Optional[float] = None


class ScenarioResult(BaseModel):
    scenario_name: str
    produce_id: str
    baseline_final_value: Optional[float] = None
    scenario_final_value: Optional[float] = None
    value_delta: Optional[float] = None
    projection: list[ScenarioProjectedPoint] = Field(default_factory=list)
    recommendation: Optional[str] = None


class ScenarioComparisonResponse(BaseModel):
    produce_id: str
    baseline: list[ScenarioProjectedPoint]
    scenarios: list[ScenarioResult]


# ---------------------------------------------------------------------------
# WebSocket broadcast payloads (websocket/manager.py)
# ---------------------------------------------------------------------------

class TwinUpdateMessage(BaseModel):
    event: Literal[
        "twin_update",
        "sensor_reading",
        "market_tick",
        "new_alert",
        "new_prediction",
        "simulation_tick",
    ]
    produce_id: Optional[str] = None
    storage_id: Optional[str] = None
    payload: dict[str, Any]
    timestamp: datetime