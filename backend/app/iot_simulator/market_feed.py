"""
market_feed.py
---------------
Simulates a live mandi (agricultural market) price feed for FarmVault's
digital twin. Baseline prices are seeded from `data/mandi_prices.csv`
(falling back to a built-in default table), then evolved tick-by-tick using
a bounded random walk with trend drift, seasonal modulation, and occasional
volatility spikes -- approximating real-world mandi price behaviour.

Consumed by `twin_core/market_twin.py` and `ai_models/price_forecaster.py`
to drive sell/hold recommendations and scenario simulations.
"""

from __future__ import annotations

import asyncio
import csv
import math
import random
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:
    from app.iot_simulator.event_bus import event_bus  # type: ignore
except ImportError:
    event_bus = None

try:
    from app.utils.logger import get_logger  # type: ignore
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MANDI_PRICES_CSV = DATA_DIR / "mandi_prices.csv"

EVENT_TOPIC = "market.price.tick"


# --------------------------------------------------------------------------
# Data models
# --------------------------------------------------------------------------
@dataclass
class MarketBaseline:
    commodity: str
    market_name: str
    state: str = "Unknown"
    modal_price_per_quintal: float = 2000.0
    min_price_per_quintal: float = 1600.0
    max_price_per_quintal: float = 2400.0
    avg_arrival_qty_quintal: float = 500.0
    volatility: float = 0.02  # relative std-dev per tick


@dataclass
class MarketPriceTick:
    tick_id: str
    commodity: str
    market_name: str
    state: str
    timestamp: str
    price_per_quintal: float
    min_price_per_quintal: float
    max_price_per_quintal: float
    arrival_qty_quintal: float
    change_pct: float

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Baseline loading
# --------------------------------------------------------------------------
_DEFAULT_BASELINES: List[MarketBaseline] = [
    MarketBaseline("tomato", "Azadpur Mandi", "Delhi", 1800, 1200, 2400, 600, 0.035),
    MarketBaseline("onion", "Lasalgaon Mandi", "Maharashtra", 2200, 1600, 2800, 1200, 0.03),
    MarketBaseline("potato", "Agra Mandi", "Uttar Pradesh", 1400, 1000, 1800, 900, 0.02),
    MarketBaseline("banana", "Koyambedu Market", "Tamil Nadu", 1600, 1200, 2000, 400, 0.025),
    MarketBaseline("mango", "Vashi APMC", "Maharashtra", 4500, 3000, 6000, 300, 0.04),
    MarketBaseline("spinach", "Koyambedu Market", "Tamil Nadu", 1200, 800, 1600, 150, 0.03),
]


def load_market_baselines() -> Dict[Tuple[str, str], MarketBaseline]:
    baselines: Dict[Tuple[str, str], MarketBaseline] = {
        (b.commodity, b.market_name): b for b in _DEFAULT_BASELINES
    }

    if not MANDI_PRICES_CSV.exists():
        logger.warning("mandi_prices.csv not found, using default market baselines")
        return baselines

    try:
        with open(MANDI_PRICES_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    commodity = row["produce"].strip().lower()
                    market_name = row.get("market_name", "Unknown Mandi").strip()
                    key = (commodity, market_name)
                    baselines[key] = MarketBaseline(
                        commodity=commodity,
                        market_name=market_name,
                        state=row.get("state", "Unknown"),
                        modal_price_per_quintal=float(row.get("modal_price", 2000)),
                        min_price_per_quintal=float(row.get("min_price", 1600)),
                        max_price_per_quintal=float(row.get("max_price", 2400)),
                        avg_arrival_qty_quintal=float(row.get("arrival_qty", 500)),
                        volatility=float(row.get("volatility", 0.025)),
                    )
                except (KeyError, ValueError) as e:
                    logger.warning(f"Skipping malformed mandi price row {row}: {e}")
    except Exception as e:
        logger.error(f"Failed to read {MANDI_PRICES_CSV}: {e}")

    return baselines


# --------------------------------------------------------------------------
# Generator
# --------------------------------------------------------------------------
class MarketFeedGenerator:
    """Simulates a live price feed for one commodity at one mandi."""

    def __init__(
        self,
        baseline: MarketBaseline,
        trend_drift_pct_per_day: float = 0.0,
        shock_probability: float = 0.01,
        noise_seed: Optional[int] = None,
    ) -> None:
        self.baseline = baseline
        self.trend_drift_pct_per_day = trend_drift_pct_per_day
        self.shock_probability = shock_probability

        self._rng = random.Random(noise_seed)
        self._current_price = baseline.modal_price_per_quintal
        self._elapsed_ticks = 0
        self._latest: Optional[MarketPriceTick] = None
        self._running = False

    def set_trend(self, drift_pct_per_day: float) -> None:
        """Allow scenario_engine.py to bias the market up/down (e.g. simulate
        a glut or shortage) without recreating the generator."""
        self.trend_drift_pct_per_day = drift_pct_per_day

    def _seasonal_multiplier(self) -> float:
        """Mild sinusoidal seasonal modulation based on day-of-year."""
        day_of_year = datetime.now(timezone.utc).timetuple().tm_yday
        return 1 + 0.05 * math.sin((2 * math.pi * day_of_year) / 365)

    def generate_tick(self, ticks_per_day: float = 288) -> MarketPriceTick:
        """Advance the price by one tick. `ticks_per_day` controls how much
        the daily trend drift contributes per call (default assumes a
        5-minute tick interval -> 288 ticks/day)."""
        self._elapsed_ticks += 1
        previous_price = self._current_price

        drift_per_tick = self.trend_drift_pct_per_day / max(ticks_per_day, 1)
        noise = self._rng.gauss(0, self.baseline.volatility)

        shock = 0.0
        if self._rng.random() < self.shock_probability:
            shock = self._rng.choice([-1, 1]) * self._rng.uniform(0.05, 0.15)
            logger.info(
                f"[market_feed] price shock on {self.baseline.commodity} @ "
                f"{self.baseline.market_name}: {shock:+.1%}"
            )

        pct_change = drift_per_tick + noise + shock
        self._current_price = max(1.0, self._current_price * (1 + pct_change))
        self._current_price *= self._seasonal_multiplier() / self._seasonal_multiplier()  # no-op smoothing hook

        change_pct = (
            ((self._current_price - previous_price) / previous_price) * 100
            if previous_price
            else 0.0
        )

        arrival_qty = max(
            0.0,
            self._rng.gauss(self.baseline.avg_arrival_qty_quintal, self.baseline.avg_arrival_qty_quintal * 0.15),
        )

        tick = MarketPriceTick(
            tick_id=str(uuid.uuid4()),
            commodity=self.baseline.commodity,
            market_name=self.baseline.market_name,
            state=self.baseline.state,
            timestamp=datetime.now(timezone.utc).isoformat(),
            price_per_quintal=round(self._current_price, 2),
            min_price_per_quintal=round(self._current_price * 0.85, 2),
            max_price_per_quintal=round(self._current_price * 1.15, 2),
            arrival_qty_quintal=round(arrival_qty, 1),
            change_pct=round(change_pct, 3),
        )
        self._latest = tick
        return tick

    def latest(self) -> Optional[MarketPriceTick]:
        return self._latest

    async def stream(
        self,
        interval_seconds: float = 10.0,
        on_tick: Optional[Callable[[MarketPriceTick], None]] = None,
    ) -> None:
        self._running = True
        ticks_per_day = 86400 / interval_seconds
        logger.info(
            f"[market_feed] streaming started for {self.baseline.commodity} @ {self.baseline.market_name}"
        )
        while self._running:
            tick = self.generate_tick(ticks_per_day=ticks_per_day)
            if event_bus is not None:
                try:
                    await event_bus.publish(EVENT_TOPIC, tick.to_dict())
                except Exception as e:
                    logger.error(f"Failed to publish market tick: {e}")
            if on_tick:
                on_tick(tick)
            await asyncio.sleep(interval_seconds)

    def stop(self) -> None:
        self._running = False


# --------------------------------------------------------------------------
# Fleet manager
# --------------------------------------------------------------------------
class MarketFeedFleet:
    def __init__(self) -> None:
        self._baselines = load_market_baselines()
        self._generators: Dict[Tuple[str, str], MarketFeedGenerator] = {}
        self._history: Dict[Tuple[str, str], List[dict]] = {}
        self._tasks: List[asyncio.Task] = []
        self._max_history = 500

    def register(self, commodity: str, market_name: str) -> MarketFeedGenerator:
        key = (commodity.lower(), market_name)
        baseline = self._baselines.get(key)
        if baseline is None:
            raise ValueError(f"No baseline found for '{commodity}' at '{market_name}'")
        gen = MarketFeedGenerator(baseline)
        self._generators[key] = gen
        self._history[key] = []
        return gen

    def get(self, commodity: str, market_name: str) -> Optional[MarketFeedGenerator]:
        return self._generators.get((commodity.lower(), market_name))

    def get_latest_price(self, commodity: str, market_name: str) -> Optional[dict]:
        gen = self.get(commodity, market_name)
        return gen.latest().to_dict() if gen and gen.latest() else None

    def get_price_history(self, commodity: str, market_name: str, limit: int = 50) -> List[dict]:
        key = (commodity.lower(), market_name)
        return self._history.get(key, [])[-limit:]

    def _record(self, key: Tuple[str, str], tick: MarketPriceTick) -> None:
        history = self._history.setdefault(key, [])
        history.append(tick.to_dict())
        if len(history) > self._max_history:
            del history[: len(history) - self._max_history]

    async def start_all(self, interval_seconds: float = 10.0) -> None:
        for key, gen in self._generators.items():
            self._tasks.append(
                asyncio.create_task(
                    gen.stream(interval_seconds, on_tick=lambda t, k=key: self._record(k, t))
                )
            )

    def stop_all(self) -> None:
        for gen in self._generators.values():
            gen.stop()
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()


market_feed_fleet = MarketFeedFleet()


if __name__ == "__main__":
    async def _demo():
        fleet = MarketFeedFleet()
        fleet.register("tomato", "Azadpur Mandi")
        gen = fleet.get("tomato", "Azadpur Mandi")
        gen.set_trend(drift_pct_per_day=-5.0)  # simulate a glut driving prices down
        for _ in range(6):
            print(gen.generate_tick().to_dict())

    asyncio.run(_demo())