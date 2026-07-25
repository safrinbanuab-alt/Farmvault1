"""
Storage models.

StorageUnit represents a physical (or simulated) storage facility such as a
cold storage room, warehouse, silo, or open-air yard. StorageReading is a
time-series log of sensor telemetry emitted by iot_simulator/storage_sensor.py,
kept so the twin and prediction models can look back at historical trends.
"""

import enum
import uuid

from sqlalchemy import (
    Column,
    String,
    Float,
    DateTime,
    Enum,
    Boolean,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class StorageType(str, enum.Enum):
    COLD_STORAGE = "cold_storage"
    WAREHOUSE = "warehouse"
    SILO = "silo"
    OPEN_AIR = "open_air"
    REFRIGERATED_TRUCK = "refrigerated_truck"
    CONTROLLED_ATMOSPHERE = "controlled_atmosphere"


class StorageUnit(Base):
    """A storage facility that holds one or more Produce batches."""

    __tablename__ = "storage_units"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    name = Column(String(100), nullable=False)
    storage_type = Column(Enum(StorageType), nullable=False, default=StorageType.WAREHOUSE)
    location = Column(String(150), nullable=True)

    # Capacity
    capacity_kg = Column(Float, nullable=False, default=0.0)
    current_load_kg = Column(Float, nullable=False, default=0.0)

    # Ideal operating ranges (used by decay_model / anomaly_detector to flag breaches)
    ideal_temp_min_c = Column(Float, nullable=True)
    ideal_temp_max_c = Column(Float, nullable=True)
    ideal_humidity_min_pct = Column(Float, nullable=True)
    ideal_humidity_max_pct = Column(Float, nullable=True)

    # Live snapshot (latest reading mirrored here for fast dashboard reads)
    current_temperature_c = Column(Float, nullable=True)
    current_humidity_pct = Column(Float, nullable=True)
    current_co2_ppm = Column(Float, nullable=True)
    current_ethylene_ppm = Column(Float, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    # Relationships
    produce_items = relationship("Produce", back_populates="storage_unit")
    readings = relationship(
        "StorageReading", back_populates="storage_unit", cascade="all, delete-orphan"
    )
    alerts = relationship(
        "Alert", back_populates="storage_unit", cascade="all, delete-orphan"
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<StorageUnit id={self.id} name={self.name!r} "
            f"type={self.storage_type} load={self.current_load_kg}/{self.capacity_kg}kg>"
        )


class StorageReading(Base):
    """A single timestamped sensor telemetry snapshot for a StorageUnit."""

    __tablename__ = "storage_readings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    storage_id = Column(String(36), ForeignKey("storage_units.id"), nullable=False, index=True)
    storage_unit = relationship("StorageUnit", back_populates="readings")

    temperature_c = Column(Float, nullable=True)
    humidity_pct = Column(Float, nullable=True)
    co2_ppm = Column(Float, nullable=True)
    ethylene_ppm = Column(Float, nullable=True)
    light_lux = Column(Float, nullable=True)

    is_anomalous = Column(Boolean, nullable=False, default=False)
    anomaly_reason = Column(Text, nullable=True)

    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<StorageReading storage_id={self.storage_id} "
            f"temp={self.temperature_c} humidity={self.humidity_pct} "
            f"at={self.recorded_at}>"
        )