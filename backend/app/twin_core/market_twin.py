"""
Market twin.

The core "digital twin" for a commodity's market behavior: trend direction,
momentum, volatility, and short-horizon price projection. Built from recent
MarketSnapshot ticks and used by recommendation_service.py and
simulation_service.py. Pure in-memory logic - never touches the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Literal, Optional

from app.models.market import MarketSnapshot

try:  # pragma: no cover - optional dependency, generated separately
    from app.ai_models.price_forecaster import forecast_price as _ai_forecast_price
except ImportError:  # pragma: no cover
    _ai_forecast_price = None


TrendDirection = Literal["up", "down", "stable"]


@dataclass
class PriceProjectionPoint:
    day: float
    projected_price_per_kg: float


class MarketTwin:
    """Wraps a commodity's recent price history with trend/volatility logic."""

    def __init__(self, commodity_name: str, snapshots: list[MarketSnapshot]):
        self.commodity_name = commodity_name
        # Keep chronological order (oldest -> newest) regardless of query order.
        self.snapshots = sorted(snapshots, key=lambda s: s.recorded_at)

    @classmethod
    def from_snapshots(cls, commodity_name: str, snapshots: list[MarketSnapshot]) -> "MarketTwin":
        return cls(commodity_name, snapshots)

    # ---------------------------------------------------------------
    # Current state
    # ---------------------------------------------------------------

    def current_price(self) -> Optional[float]:
        if not self.snapshots:
            return None
        return self.snapshots[-1].price_per_kg

    def price_series(self) -> list[float]:
        return [s.price_per_kg for s in self.snapshots]

    def has_data(self) -> bool:
        return len(self.snapshots) > 0

    # ---------------------------------------------------------------
    # Trend / volatility
    # ---------------------------------------------------------------

    def trend_direction(self, lookback: int = 5) -> TrendDirection:
        series = self.price_series()[-lookback:]
        if len(series) < 2 or not series[0]:
            return "stable"

        change_pct = (series[-1] - series[0]) / series[0] * 100
        if change_pct > 2:
            return "up"
        if change_pct < -2:
            return "down"
        return "stable"

    def momentum_pct(self, lookback: int = 5) -> Optional[float]:
        """% price change over the last `lookback` snapshots."""

        series = self.price_series()[-lookback:]
        if len(series) < 2 or not series[0]:
            return None
        return round((series[-1] - series[0]) / series[0] * 100, 2)

    def volatility_pct(self, lookback: int = 10) -> Optional[float]:
        """Standard deviation of recent prices as a % of the mean - a simple,
        model-free volatility proxy for the dashboard/alerts."""

        series = self.price_series()[-lookback:]
        if len(series) < 2:
            return None
        avg = mean(series)
        if not avg:
            return None
        return round((pstdev(series) / avg) * 100, 2)

    def is_volatile(self, threshold_pct: float = 10.0, lookback: int = 10) -> bool:
        vol = self.volatility_pct(lookback)
        return vol is not None and vol >= threshold_pct

    # ---------------------------------------------------------------
    # Projection
    # ---------------------------------------------------------------

    def project(self, days: float, step: float = 1.0) -> list[PriceProjectionPoint]:
        """Non-destructive short-horizon price projection. Delegates to
        ai_models.price_forecaster when available, otherwise linearly
        extrapolates recent momentum, damped so it doesn't run away over a
        long horizon."""

        if _ai_forecast_price is not None:
            try:
                result = _ai_forecast_price(
                    commodity_name=self.commodity_name, horizon_days=days
                )
                return [
                    PriceProjectionPoint(day=p["day"], projected_price_per_kg=p["price_per_kg"])
                    for p in result
                ]
            except Exception:
                pass  # fall through to heuristic

        current = self.current_price()
        if current is None:
            return []

        daily_drift_pct = (self.momentum_pct() or 0.0) / 5.0  # damped daily drift
        points: list[PriceProjectionPoint] = []
        elapsed = 0.0
        price = current
        while elapsed <= days:
            points.append(
                PriceProjectionPoint(day=round(elapsed, 2), projected_price_per_kg=round(price, 2))
            )
            price = max(0.0, price * (1 + daily_drift_pct / 100))
            elapsed += step
        return points

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "commodity_name": self.commodity_name,
            "current_price_per_kg": self.current_price(),
            "trend_direction": self.trend_direction(),
            "momentum_pct": self.momentum_pct(),
            "volatility_pct": self.volatility_pct(),
            "is_volatile": self.is_volatile(),
            "sample_size": len(self.snapshots),
            "as_of": datetime.now(timezone.utc).isoformat(),
        }