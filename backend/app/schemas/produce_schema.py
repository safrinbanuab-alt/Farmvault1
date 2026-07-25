"""
Produce schemas.

Pydantic models used by api/patient_routes.py -> actually api/... (produce
endpoints), services/produce_service.py, and twin_core/produce_twin.py to
validate requests and shape responses for a Produce batch.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.produce import ProduceCategory, QualityGrade, ProduceStage


# ---------------------------------------------------------------------------
# Shared / base
# ---------------------------------------------------------------------------

class ProduceBase(BaseModel):
    name: str = Field(..., max_length=100, examples=["Tomato"])
    variety: Optional[str] = Field(None, max_length=100, examples=["Roma"])
    category: ProduceCategory = ProduceCategory.OTHER
    batch_code: Optional[str] = Field(None, max_length=50)

    quantity_kg: float = Field(..., ge=0)
    unit: str = Field("kg", max_length=20)

    farmer_name: Optional[str] = Field(None, max_length=120)
    farm_location: Optional[str] = Field(None, max_length=150)
    harvest_date: Optional[datetime] = None

    initial_price_per_kg: Optional[float] = Field(None, ge=0)


# ---------------------------------------------------------------------------
# Create / Update
# ---------------------------------------------------------------------------

class ProduceCreate(ProduceBase):
    storage_id: Optional[str] = None
    quality_grade: QualityGrade = QualityGrade.A
    moisture_content: Optional[float] = Field(None, ge=0, le=100)
    is_simulated: bool = True
    notes: Optional[str] = None


class ProduceUpdate(BaseModel):
    """All fields optional - used for PATCH."""

    name: Optional[str] = Field(None, max_length=100)
    variety: Optional[str] = Field(None, max_length=100)
    category: Optional[ProduceCategory] = None

    quantity_kg: Optional[float] = Field(None, ge=0)
    storage_id: Optional[str] = None

    quality_grade: Optional[QualityGrade] = None
    current_stage: Optional[ProduceStage] = None
    decay_percent: Optional[float] = Field(None, ge=0, le=100)
    moisture_content: Optional[float] = Field(None, ge=0, le=100)
    shelf_life_days_estimate: Optional[float] = Field(None, ge=0)

    current_estimated_value: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None


class ProduceDecayUpdate(BaseModel):
    """Narrow payload used by the simulation clock / decay_model to push a tick."""

    decay_percent: float = Field(..., ge=0, le=100)
    current_stage: ProduceStage
    days_since_harvest: float = Field(..., ge=0)
    shelf_life_days_estimate: Optional[float] = Field(None, ge=0)
    moisture_content: Optional[float] = Field(None, ge=0, le=100)


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class ProduceSummary(BaseModel):
    """Lightweight shape for list views / dashboard cards."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: ProduceCategory
    quantity_kg: float
    current_stage: ProduceStage
    quality_grade: QualityGrade
    decay_percent: float
    current_estimated_value: Optional[float] = None


class ProduceResponse(ProduceBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    initial_quantity_kg: float
    storage_id: Optional[str] = None

    quality_grade: QualityGrade
    current_stage: ProduceStage
    decay_percent: float
    moisture_content: Optional[float] = None
    shelf_life_days_estimate: Optional[float] = None
    days_since_harvest: float

    current_estimated_value: Optional[float] = None
    is_simulated: bool
    notes: Optional[str] = None

    created_at: datetime
    updated_at: datetime


class ProduceListResponse(BaseModel):
    total: int
    items: list[ProduceSummary]