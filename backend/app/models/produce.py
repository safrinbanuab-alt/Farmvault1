"""
Produce model.

Represents a single batch/lot of agricultural produce being tracked by its
digital twin. This is the root entity that Storage, Prediction, and Alert
records hang off of.
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
    Boolean,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ProduceCategory(str, enum.Enum):
    FRUIT = "fruit"
    VEGETABLE = "vegetable"
    GRAIN = "grain"
    PULSE = "pulse"
    SPICE = "spice"
    DAIRY = "dairy"
    OTHER = "other"


class QualityGrade(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    REJECTED = "rejected"


class ProduceStage(str, enum.Enum):
    HARVESTED = "harvested"
    FRESH = "fresh"
    RIPENING = "ripening"
    PEAK = "peak"
    DECAYING = "decaying"
    SPOILED = "spoiled"
    SOLD = "sold"
    DISPOSED = "disposed"


class Produce(Base):
    """A tracked batch of produce and the live state of its digital twin."""

    __tablename__ = "produce"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Identity
    name = Column(String(100), nullable=False, index=True)
    variety = Column(String(100), nullable=True)
    category = Column(Enum(ProduceCategory), nullable=False, default=ProduceCategory.OTHER)
    batch_code = Column(String(50), unique=True, nullable=True, index=True)

    # Quantity
    quantity_kg = Column(Float, nullable=False, default=0.0)
    initial_quantity_kg = Column(Float, nullable=False, default=0.0)
    unit = Column(String(20), nullable=False, default="kg")

    # Origin
    farmer_name = Column(String(120), nullable=True)
    farm_location = Column(String(150), nullable=True)
    harvest_date = Column(DateTime(timezone=True), nullable=True)

    # Quality / decay state (driven by twin_core + ai_models/decay_model.py)
    quality_grade = Column(Enum(QualityGrade), nullable=False, default=QualityGrade.A)
    current_stage = Column(Enum(ProduceStage), nullable=False, default=ProduceStage.HARVESTED)
    decay_percent = Column(Float, nullable=False, default=0.0)  # 0-100
    moisture_content = Column(Float, nullable=True)  # percentage
    shelf_life_days_estimate = Column(Float, nullable=True)
    days_since_harvest = Column(Float, nullable=False, default=0.0)

    # Economics
    initial_price_per_kg = Column(Float, nullable=True)
    current_estimated_value = Column(Float, nullable=True)

    # Relationships
    storage_id = Column(String(36), ForeignKey("storage_units.id"), nullable=True)
    storage_unit = relationship("StorageUnit", back_populates="produce_items")

    predictions = relationship(
        "Prediction", back_populates="produce", cascade="all, delete-orphan"
    )
    alerts = relationship(
        "Alert", back_populates="produce", cascade="all, delete-orphan"
    )

    # Simulation / twin bookkeeping
    is_simulated = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Produce id={self.id} name={self.name!r} "
            f"stage={self.current_stage} decay={self.decay_percent}%>"
        )