"""
Prediction model.

Stores the output of the ai_models/* modules (decay_model, price_forecaster,
anomaly_detector, optimizer) each time they run against a Produce batch, so
the frontend can show historical prediction accuracy and explainability
(explainable_ai.py) alongside the current forecast.
"""

import enum
import uuid

from sqlalchemy import (
    Column,
    String,
    Float,
    DateTime,
    Enum,
    ForeignKey,
    Text,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class PredictionType(str, enum.Enum):
    DECAY = "decay"
    PRICE = "price"
    ANOMALY = "anomaly"
    OPTIMAL_ACTION = "optimal_action"  # e.g. "sell now" / "move to cold storage"
    SHELF_LIFE = "shelf_life"


class PredictionModel(str, enum.Enum):
    DECAY_MODEL = "decay_model"
    PRICE_FORECASTER = "price_forecaster"
    ANOMALY_DETECTOR = "anomaly_detector"
    OPTIMIZER = "optimizer"


class Prediction(Base):
    """A single AI model inference result tied to a Produce batch."""

    __tablename__ = "predictions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    produce_id = Column(String(36), ForeignKey("produce.id"), nullable=False, index=True)
    produce = relationship("Produce", back_populates="predictions")

    prediction_type = Column(Enum(PredictionType), nullable=False)
    model_name = Column(Enum(PredictionModel), nullable=False)
    model_version = Column(String(30), nullable=True, default="v1")

    # Core forecast output
    predicted_value = Column(Float, nullable=True)  # e.g. decay %, price/kg, risk score
    predicted_label = Column(String(100), nullable=True)  # e.g. "spoiled", "sell", "hold"
    confidence_score = Column(Float, nullable=True)  # 0-1

    predicted_for_date = Column(DateTime(timezone=True), nullable=True)
    horizon_days = Column(Float, nullable=True)  # how far ahead this prediction looks

    # Explainability (from explainable_ai.py)
    input_features = Column(JSON, nullable=True)
    feature_importance = Column(JSON, nullable=True)
    explanation = Column(Text, nullable=True)

    # Backtesting / accuracy tracking, filled in later once ground truth is known
    actual_value = Column(Float, nullable=True)
    error_margin = Column(Float, nullable=True)

    generated_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Prediction produce_id={self.produce_id} type={self.prediction_type} "
            f"value={self.predicted_value} confidence={self.confidence_score}>"
        )