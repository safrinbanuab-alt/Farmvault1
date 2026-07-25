"""
Prediction schemas.

Pydantic models used by api/prediction_routes.py and services that call into
ai_models/* (decay_model, price_forecaster, anomaly_detector, optimizer,
explainable_ai) to validate prediction requests and shape prediction results.
"""

from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.prediction import PredictionType, PredictionModel


# ---------------------------------------------------------------------------
# Request schemas (trigger a model run)
# ---------------------------------------------------------------------------

class DecayPredictionRequest(BaseModel):
    produce_id: str
    horizon_days: float = Field(7, ge=0, le=90, description="How many days ahead to forecast")


class PricePredictionRequest(BaseModel):
    produce_id: Optional[str] = None
    commodity_name: str
    mandi_name: Optional[str] = None
    horizon_days: float = Field(7, ge=0, le=90)


class AnomalyDetectionRequest(BaseModel):
    storage_id: Optional[str] = None
    produce_id: Optional[str] = None
    lookback_hours: float = Field(24, ge=1, le=720)


class OptimalActionRequest(BaseModel):
    produce_id: str
    """Ask optimizer.py what to do with a batch: sell / hold / relocate / discount."""


# ---------------------------------------------------------------------------
# Explainability
# ---------------------------------------------------------------------------

class FeatureImportance(BaseModel):
    feature_name: str
    importance: float = Field(..., ge=0, le=1)


class PredictionExplanation(BaseModel):
    summary: str
    feature_importance: list[FeatureImportance] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Create / persist
# ---------------------------------------------------------------------------

class PredictionCreate(BaseModel):
    produce_id: str
    prediction_type: PredictionType
    model_name: PredictionModel
    model_version: Optional[str] = "v1"

    predicted_value: Optional[float] = None
    predicted_label: Optional[str] = None
    confidence_score: Optional[float] = Field(None, ge=0, le=1)

    predicted_for_date: Optional[datetime] = None
    horizon_days: Optional[float] = Field(None, ge=0)

    input_features: Optional[dict[str, Any]] = None
    feature_importance: Optional[dict[str, Any]] = None
    explanation: Optional[str] = None


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class PredictionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    produce_id: str
    prediction_type: PredictionType
    model_name: PredictionModel
    model_version: Optional[str] = None

    predicted_value: Optional[float] = None
    predicted_label: Optional[str] = None
    confidence_score: Optional[float] = None

    predicted_for_date: Optional[datetime] = None
    horizon_days: Optional[float] = None

    explanation: Optional[str] = None
    feature_importance: Optional[dict[str, Any]] = None

    actual_value: Optional[float] = None
    error_margin: Optional[float] = None

    generated_at: datetime


class PredictionAccuracyResponse(BaseModel):
    """Aggregate accuracy stats for a model, used on Analytics.jsx."""

    model_name: PredictionModel
    prediction_type: PredictionType
    sample_size: int
    mean_absolute_error: Optional[float] = None
    average_confidence: Optional[float] = None