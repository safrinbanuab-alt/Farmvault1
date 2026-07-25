"""
Alert model.

Represents an actionable notification raised either by the IoT anomaly
injector, the AI anomaly_detector/decay_model, or the recommendation_service,
and surfaced to the frontend AlertPanel component in real time via the
websocket manager.
"""

import enum
import uuid

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Enum,
    Boolean,
    ForeignKey,
    Text,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class AlertType(str, enum.Enum):
    DECAY_RISK = "decay_risk"
    SPOILAGE_IMMINENT = "spoilage_imminent"
    TEMPERATURE_BREACH = "temperature_breach"
    HUMIDITY_BREACH = "humidity_breach"
    PRICE_DROP = "price_drop"
    PRICE_SPIKE = "price_spike"
    ANOMALY_DETECTED = "anomaly_detected"
    STORAGE_CAPACITY = "storage_capacity"
    RECOMMENDED_ACTION = "recommended_action"
    SENSOR_FAILURE = "sensor_failure"


class AlertSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertSource(str, enum.Enum):
    IOT_SIMULATOR = "iot_simulator"
    AI_MODEL = "ai_model"
    RECOMMENDATION_ENGINE = "recommendation_engine"
    MANUAL = "manual"
    SYSTEM = "system"


class Alert(Base):
    """A notification/alert tied to a Produce batch and/or a StorageUnit."""

    __tablename__ = "alerts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    produce_id = Column(String(36), ForeignKey("produce.id"), nullable=True, index=True)
    produce = relationship("Produce", back_populates="alerts")

    storage_id = Column(String(36), ForeignKey("storage_units.id"), nullable=True, index=True)
    storage_unit = relationship("StorageUnit", back_populates="alerts")

    alert_type = Column(Enum(AlertType), nullable=False)
    severity = Column(Enum(AlertSeverity), nullable=False, default=AlertSeverity.MEDIUM)
    source = Column(Enum(AlertSource), nullable=False, default=AlertSource.SYSTEM)

    title = Column(String(150), nullable=False)
    message = Column(Text, nullable=False)
    extra_data = Column(JSON, nullable=True)  # e.g. sensor values, thresholds breached

    is_resolved = Column(Boolean, nullable=False, default=False)
    is_acknowledged = Column(Boolean, nullable=False, default=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    triggered_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Alert id={self.id} type={self.alert_type} "
            f"severity={self.severity} resolved={self.is_resolved}>"
        )