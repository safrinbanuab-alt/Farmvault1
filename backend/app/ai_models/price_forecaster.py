"""
price_forecaster.py

Analyzes mandi (market) price history and projects prices forward. Used by
twin_core/scenario_engine.py to price out "sell now vs hold" scenarios, and
by services/market_service.py / api/market_routes.py to power price charts
and trend badges (components/PriceChart.jsx).

Model
-----
For a given produce (and optionally a specific market/mandi), the forecaster:
  1. Loads historical price points from backend/app/data/mandi_prices.csv
     (columns: date, produce_id, produce_name, market, price_per_kg).
  2. Fits a simple linear trend (least squares) over a recent lookback
     window to capture the current price direction.
  3. Adds a mild seasonal wave (deterministic per produce) to reflect the
     harvest-cycle price swings mandi data typically shows.
  4. Applies any demand/supply/price "shock" percentages supplied by a
     scenario, ramped in over the first few days rather than jumping
     instantly, which better matches how mandi prices actually discover a
     new equilibrium.

If no historical data is available for a produce, the forecaster falls back
to a built-in base price table so it always returns a usable number rather
than failing -- scenario planning shouldn't be blocked on data completeness.
"""

from __future__ import annotations

import csv
import logging
import math
import os
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("farmvault.ai_models.price_forecaster")

_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y")


def _parse_date(raw: str) -> Optional[date]:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    logger.debug("Could not parse date '%s' with known formats", raw)
    return None


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass
class PricePoint:
    price_date: date
    price_per_kg: float
    market: str = "default"


@dataclass
class MarketPriceSeries:
    produce_id: str
    produce_name: str
    market: str
    history: List[PricePoint] = field(default_factory=list)

    def sorted_history(self) -> List[PricePoint]:
        return sorted(self.history, key=lambda p: p.price_date)

    def latest(self) -> Optional[PricePoint]:
        sorted_points = self.sorted_history()
        return sorted_points[-1] if sorted_points else None

    def recent(self, lookback_days: int) -> List[PricePoint]:
        points = self.sorted_history()
        if not points:
            return []
        cutoff = points[-1].price_date - timedelta(days=lookback_days)
        return [p for p in points if p.price_date >= cutoff]


# Fallback base prices (INR/kg) used when no historical CSV data exists for
# a produce. Deliberately conservative, representative mandi averages.
DEFAULT_BASE_PRICES: Dict[str, float] = {
    "tomato": 18.0,
    "potato": 14.0,
    "onion": 20.0,
    "onion_bulb": 20.0,
    "banana": 22.0,
    "mango": 45.0,
    "leafy_greens": 25.0,
    "grapes": 55.0,
    "generic": 20.0,
}


class PriceForecaster:
    """Loads/holds market price history and forecasts forward prices."""

    def __init__(
        self,
        data_path: Optional[str] = None,
        default_base_price: float = 20.0,
        seasonal_amplitude_pct: float = 8.0,
        default_trend_lookback_days: int = 30,
        shock_ramp_days: float = 3.0,
    ) -> None:
        # Keyed by (produce_id, market); "default" market bucket used when
        # no specific mandi is requested or present in the source data.
        self._series: Dict[Tuple[str, str], MarketPriceSeries] = {}
        self._alias_index: Dict[str, str] = {}
        self._default_base_price = default_base_price
        self._seasonal_amplitude_pct = seasonal_amplitude_pct
        self._default_trend_lookback_days = default_trend_lookback_days
        self._shock_ramp_days = max(shock_ramp_days, 0.01)

        self._load_history(data_path)

    # ------------------------------------------------------------ loading
    def _candidate_paths(self) -> List[str]:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, "..", "app", "data", "mandi_prices.csv"),
            os.path.join(here, "..", "data", "mandi_prices.csv"),
            os.path.join(here, "data", "mandi_prices.csv"),
        ]
        return [os.path.normpath(c) for c in candidates]

    def _load_history(self, data_path: Optional[str]) -> None:
        paths_to_try = ([data_path] if data_path else []) + self._candidate_paths()
        loaded_from = None
        for path in paths_to_try:
            if path and os.path.isfile(path):
                try:
                    self._load_csv(path)
                    loaded_from = path
                    break
                except Exception:
                    logger.exception("Failed to parse mandi price CSV at %s", path)

        if loaded_from is None:
            logger.info(
                "No mandi_prices.csv found (checked %s) -- forecasts will use "
                "built-in base prices with trend/seasonality only",
                ", ".join(paths_to_try) if paths_to_try else "(no candidate paths)",
            )

    def _load_csv(self, path: str) -> None:
        count = 0
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                produce_id = (row.get("produce_id") or "").strip()
                if not produce_id:
                    continue
                produce_name = (row.get("produce_name") or produce_id).strip()
                market = (row.get("market") or "default").strip() or "default"

                price_raw = row.get("price_per_kg") or row.get("price") or row.get("modal_price")
                try:
                    price_per_kg = float(price_raw)
                except (TypeError, ValueError):
                    continue

                price_date = _parse_date(row.get("date", ""))
                if price_date is None:
                    continue

                key = (produce_id, market)
                series = self._series.get(key)
                if series is None:
                    series = MarketPriceSeries(
                        produce_id=produce_id, produce_name=produce_name, market=market
                    )
                    self._series[key] = series
                series.history.append(PricePoint(price_date=price_date, price_per_kg=price_per_kg, market=market))
                self._alias_index[produce_name.strip().lower()] = produce_id
                count += 1
        logger.info("Loaded %d mandi price point(s) from %s", count, path)

    # ------------------------------------------------------------- lookup
    def register_price_point(
        self, produce_id: str, produce_name: str, price_date: date, price_per_kg: float, market: str = "default"
    ) -> None:
        """Add a live/manual price point at runtime (e.g. from a market feed
        event bus tick) without needing to reload the CSV."""
        key = (produce_id, market)
        series = self._series.get(key)
        if series is None:
            series = MarketPriceSeries(produce_id=produce_id, produce_name=produce_name, market=market)
            self._series[key] = series
        series.history.append(PricePoint(price_date=price_date, price_per_kg=price_per_kg, market=market))
        self._alias_index[produce_name.strip().lower()] = produce_id

    def _resolve_produce_id(self, produce_id: str) -> str:
        if any(pid == produce_id for pid, _ in self._series.keys()):
            return produce_id
        alias = self._alias_index.get(produce_id.strip().lower())
        return alias or produce_id

    def get_series(self, produce_id: str, market: Optional[str] = None) -> Optional[MarketPriceSeries]:
        resolved_id = self._resolve_produce_id(produce_id)

        if market:
            return self._series.get((resolved_id, market))

        # No market specified: prefer "default", otherwise the series with
        # the most history for that produce across all markets.
        candidates = [s for (pid, _mkt), s in self._series.items() if pid == resolved_id]
        if not candidates:
            return None
        default_series = next((s for s in candidates if s.market == "default"), None)
        if default_series is not None:
            return default_series
        return max(candidates, key=lambda s: len(s.history))

    def list_supported_produce(self) -> List[str]:
        return sorted({pid for pid, _mkt in self._series.keys()})

    # ---------------------------------------------------------- analytics
    def get_price_history(self, produce_id: str, market: Optional[str] = None) -> List[PricePoint]:
        series = self.get_series(produce_id, market)
        return series.sorted_history() if series else []

    def get_current_price(self, produce_id: str, market: Optional[str] = None) -> float:
        series = self.get_series(produce_id, market)
        latest = series.latest() if series else None
        if latest is not None:
            return latest.price_per_kg
        resolved_id = self._resolve_produce_id(produce_id)
        return DEFAULT_BASE_PRICES.get(resolved_id.lower(), self._default_base_price)

    @staticmethod
    def _linear_regression(xs: List[float], ys: List[float]) -> Tuple[float, float]:
        """Ordinary least-squares slope/intercept, pure stdlib (no numpy
        dependency). Returns (slope, intercept)."""
        n = len(xs)
        if n < 2:
            return 0.0, (ys[0] if ys else 0.0)

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denominator = sum((x - mean_x) ** 2 for x in xs)
        if denominator == 0:
            return 0.0, mean_y

        slope = numerator / denominator
        intercept = mean_y - slope * mean_x
        return slope, intercept

    def compute_trend_per_day(
        self, produce_id: str, market: Optional[str] = None, lookback_days: Optional[int] = None
    ) -> float:
        """Recent price trend in currency units per day (positive = rising,
        negative = falling), fit by least squares over the lookback window."""
        series = self.get_series(produce_id, market)
        if series is None:
            return 0.0

        window = lookback_days if lookback_days is not None else self._default_trend_lookback_days
        points = series.recent(window)
        if len(points) < 2:
            return 0.0

        base_date = points[0].price_date
        xs = [(p.price_date - base_date).days for p in points]
        ys = [p.price_per_kg for p in points]
        slope, _intercept = self._linear_regression(xs, ys)
        return slope

    def compute_volatility(
        self, produce_id: str, market: Optional[str] = None, lookback_days: Optional[int] = None
    ) -> float:
        """Standard deviation of day-over-day percentage price changes over
        the lookback window -- a simple volatility proxy for flagging
        unstable markets (used to widen confidence bands in the UI)."""
        series = self.get_series(produce_id, market)
        if series is None:
            return 0.0

        window = lookback_days if lookback_days is not None else self._default_trend_lookback_days
        points = series.recent(window)
        if len(points) < 3:
            return 0.0

        prices = [p.price_per_kg for p in points]
        pct_changes = [
            (prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(1, len(prices))
            if prices[i - 1] > 0
        ]
        if len(pct_changes) < 2:
            return 0.0
        return statistics.pstdev(pct_changes) * 100.0

    def _seasonal_factor(self, produce_id: str, day_offset: float) -> float:
        """Deterministic pseudo-seasonal wave (fraction of price, e.g. 0.03
        = +3%) so different produce don't all peak/trough on the same days.
        Phase is derived from a stable hash of the produce id."""
        phase_seed = sum(ord(c) for c in produce_id) % 365
        angle = 2 * math.pi * ((day_offset + phase_seed) / 365.0)
        return (self._seasonal_amplitude_pct / 100.0) * math.sin(angle)

    # --------------------------------------------------------- forecasting
    def forecast_price(
        self,
        produce_id: str,
        day_offset: float = 0,
        market: Optional[str] = None,
        demand_shock_pct: float = 0.0,
        supply_shock_pct: float = 0.0,
        price_shock_pct: float = 0.0,
    ) -> float:
        """Project the price `day_offset` days from the latest known/base
        price. Trend and seasonality are always applied; demand/supply/price
        shocks are additional scenario-specific adjustments (see
        twin_core/scenario_engine.py) that ramp in over
        `shock_ramp_days` rather than applying instantly."""
        base_price = self.get_current_price(produce_id, market)
        trend_per_day = self.compute_trend_per_day(produce_id, market)

        trend_component = trend_per_day * day_offset
        seasonal_component = base_price * self._seasonal_factor(produce_id, day_offset)

        ramp = min(1.0, day_offset / self._shock_ramp_days) if day_offset > 0 else 0.0
        net_shock_pct = (price_shock_pct + demand_shock_pct - supply_shock_pct) * ramp

        projected = (base_price + trend_component + seasonal_component) * (1.0 + net_shock_pct / 100.0)
        return max(0.0, projected)

    # Aliases for interface compatibility with different caller conventions
    # (twin_core/scenario_engine.py probes for any of these method names).
    def forecast(self, produce_id: str, day_offset: float = 0, **kwargs) -> float:
        return self.forecast_price(produce_id, day_offset, **kwargs)

    def predict_price(self, produce_id: str, day_offset: float = 0, **kwargs) -> float:
        return self.forecast_price(produce_id, day_offset, **kwargs)

    def forecast_series(
        self,
        produce_id: str,
        days: int,
        market: Optional[str] = None,
        demand_shock_pct: float = 0.0,
        supply_shock_pct: float = 0.0,
        price_shock_pct: float = 0.0,
    ) -> List[Tuple[int, float]]:
        """Day-by-day forecast points, used to draw the price forecast line
        in components/PriceChart.jsx."""
        return [
            (
                day,
                round(
                    self.forecast_price(
                        produce_id,
                        day_offset=day,
                        market=market,
                        demand_shock_pct=demand_shock_pct,
                        supply_shock_pct=supply_shock_pct,
                        price_shock_pct=price_shock_pct,
                    ),
                    2,
                ),
            )
            for day in range(days + 1)
        ]

    def get_market_summary(self, produce_id: str, market: Optional[str] = None) -> dict:
        """One-shot bundle of current price, trend, volatility, and a plain
        text recommendation, used by services/dashboard_service.py to
        populate market cards (components/MarketCard.jsx)."""
        current_price = self.get_current_price(produce_id, market)
        trend_per_day = self.compute_trend_per_day(produce_id, market)
        volatility_pct = self.compute_volatility(produce_id, market)

        if trend_per_day > 0.05 * max(current_price, 1e-6):
            recommendation = "Prices are trending up -- holding stock may improve returns."
        elif trend_per_day < -0.05 * max(current_price, 1e-6):
            recommendation = "Prices are trending down -- selling sooner may be preferable."
        else:
            recommendation = "Prices are relatively stable -- timing is less critical."

        return {
            "produce_id": self._resolve_produce_id(produce_id),
            "market": market or "default",
            "current_price_per_kg": round(current_price, 2),
            "trend_per_day": round(trend_per_day, 4),
            "volatility_pct": round(volatility_pct, 2),
            "recommendation": recommendation,
        }


if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO)

    forecaster = PriceForecaster()

    # Seed some synthetic history for a demo produce since no CSV is present
    # in this standalone run.
    random.seed(42)
    today = date.today()
    price = 18.0
    for i in range(30, 0, -1):
        price = max(5.0, price + random.uniform(-0.6, 0.7))
        forecaster.register_price_point(
            produce_id="tomato",
            produce_name="Tomato",
            price_date=today - timedelta(days=i),
            price_per_kg=round(price, 2),
        )

    print("Supported produce:", forecaster.list_supported_produce())
    print("Market summary:", forecaster.get_market_summary("tomato"))

    for offset in (0, 3, 7, 14):
        baseline = forecaster.forecast_price("tomato", day_offset=offset)
        with_demand_spike = forecaster.forecast_price(
            "tomato", day_offset=offset, demand_shock_pct=15.0
        )
        print(f"day {offset:>2}: baseline={baseline:.2f}  demand+15%={with_demand_spike:.2f}")

    print("Unlisted produce falls back to base price:", forecaster.get_current_price("dragonfruit"))