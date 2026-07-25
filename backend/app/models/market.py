"""
Market models.

MandiPrice stores historical/reference mandi (wholesale market) price records,
typically seeded from data/mandi_prices.csv. MarketSnapshot stores live/simulated
ticks produced by iot_simulator/market_feed.py so the twin can compare a
produce batch's estimated value against the current market in near real time.
"""

import enum
import uuid

from sqlalchemy import (
    Column,
    String,
    Float,
    DateTime,
    Enum,
    Integer,
)
from sqlalchemy.sql import func

from app.database import Base


class PriceUnit(str, enum.Enum):
    PER_KG = "per_kg"
    PER_QUINTAL = "per_quintal"
    PER_TONNE = "per_tonne"
    PER_UNIT = "per_unit"


class MandiPrice(Base):
    """Reference wholesale market price record for a commodity at a mandi."""

    __tablename__ = "mandi_prices"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    commodity_name = Column(String(100), nullable=False, index=True)
    variety = Column(String(100), nullable=True)

    mandi_name = Column(String(150), nullable=False, index=True)
    state = Column(String(100), nullable=True)
    district = Column(String(100), nullable=True)

    min_price = Column(Float, nullable=True)
    max_price = Column(Float, nullable=True)
    modal_price = Column(Float, nullable=True)  # most commonly traded price
    unit = Column(Enum(PriceUnit), nullable=False, default=PriceUnit.PER_QUINTAL)

    arrival_quantity = Column(Float, nullable=True)  # quantity that arrived at mandi
    price_date = Column(DateTime(timezone=True), nullable=False, index=True)

    source = Column(String(80), nullable=True, default="agmarknet")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<MandiPrice {self.commodity_name!r} @ {self.mandi_name!r} "
            f"modal={self.modal_price} date={self.price_date}>"
        )


class MarketSnapshot(Base):
    """
    A live/simulated market tick emitted by the iot_simulator market feed.
    Used for real-time charts and as an input feature to price_forecaster.py.
    """

    __tablename__ = "market_snapshots"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    commodity_name = Column(String(100), nullable=False, index=True)
    mandi_name = Column(String(150), nullable=True)

    price_per_kg = Column(Float, nullable=False)
    demand_index = Column(Float, nullable=True)  # 0-100 relative demand indicator
    supply_index = Column(Float, nullable=True)  # 0-100 relative supply indicator
    volatility_pct = Column(Float, nullable=True)

    trend_direction = Column(String(20), nullable=True)  # "up" | "down" | "stable"

    tick_sequence = Column(Integer, nullable=True)  # simulation clock tick number

    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<MarketSnapshot {self.commodity_name!r} "
            f"price={self.price_per_kg} trend={self.trend_direction}>"
        )