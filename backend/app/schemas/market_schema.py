"""
Market schemas.

Pydantic models used by api/market_routes.py, services/market_service.py, and
iot_simulator/market_feed.py to validate mandi price records and live market
snapshots.
"""

from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.market import PriceUnit


# ---------------------------------------------------------------------------
# MandiPrice (reference / historical)
# ---------------------------------------------------------------------------

class MandiPriceBase(BaseModel):
    commodity_name: str = Field(..., max_length=100, examples=["Tomato"])
    variety: Optional[str] = Field(None, max_length=100)

    mandi_name: str = Field(..., max_length=150, examples=["Coimbatore Mandi"])
    state: Optional[str] = Field(None, max_length=100)
    district: Optional[str] = Field(None, max_length=100)

    min_price: Optional[float] = Field(None, ge=0)
    max_price: Optional[float] = Field(None, ge=0)
    modal_price: Optional[float] = Field(None, ge=0)
    unit: PriceUnit = PriceUnit.PER_QUINTAL

    arrival_quantity: Optional[float] = Field(None, ge=0)
    price_date: datetime


class MandiPriceCreate(MandiPriceBase):
    source: Optional[str] = Field("agmarknet", max_length=80)


class MandiPriceResponse(MandiPriceBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# MarketSnapshot (live / simulated ticks)
# ---------------------------------------------------------------------------

class MarketSnapshotBase(BaseModel):
    commodity_name: str = Field(..., max_length=100)
    mandi_name: Optional[str] = Field(None, max_length=150)

    price_per_kg: float = Field(..., ge=0)
    demand_index: Optional[float] = Field(None, ge=0, le=100)
    supply_index: Optional[float] = Field(None, ge=0, le=100)
    volatility_pct: Optional[float] = Field(None, ge=0)

    trend_direction: Optional[Literal["up", "down", "stable"]] = None


class MarketSnapshotCreate(MarketSnapshotBase):
    tick_sequence: Optional[int] = None


class MarketSnapshotResponse(MarketSnapshotBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tick_sequence: Optional[int] = None
    recorded_at: datetime


# ---------------------------------------------------------------------------
# Derived / dashboard views
# ---------------------------------------------------------------------------

class MarketTrendPoint(BaseModel):
    """A single point used to render PriceChart.jsx."""

    timestamp: datetime
    price_per_kg: float


class MarketTrendResponse(BaseModel):
    commodity_name: str
    points: list[MarketTrendPoint]
    current_price_per_kg: Optional[float] = None
    change_pct_24h: Optional[float] = None


class ProduceMarketComparison(BaseModel):
    """
    Compares a produce batch's estimated value against the current market
    price for its commodity - used by recommendation_service.py.
    """

    produce_id: str
    commodity_name: str
    produce_estimated_value_per_kg: Optional[float] = None
    market_price_per_kg: Optional[float] = None
    variance_pct: Optional[float] = None
    recommendation: Optional[str] = None  # e.g. "sell_now", "hold", "move_storage"