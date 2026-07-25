"""
market_routes.py
-----------------
Exposes FarmVault's live mandi (agricultural market) price feed to the
frontend: current prices, price history for charting, registering new
commodity/market feeds, and demo/testing hooks to simulate price shocks.

Backed directly by `iot_simulator/market_feed.py`'s `market_feed_fleet`
singleton and, for shock simulation, `iot_simulator/anomaly_injector.py`.

The `/recommendations` endpoint uses a simple trend heuristic as a
placeholder -- once `ai_models/price_forecaster.py` exists it should
replace this logic with real forecasted sell/hold guidance.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from app.utils.logger import get_logger  # type: ignore
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

from app.iot_simulator.market_feed import market_feed_fleet
from app.iot_simulator.anomaly_injector import anomaly_injector

router = APIRouter(prefix="/api/market", tags=["Market"])

_feed_tasks: Dict[Tuple[str, str], asyncio.Task] = {}


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class FeedRegisterRequest(BaseModel):
    commodity: str = Field(..., description="e.g. 'tomato'")
    market_name: str = Field(..., description="e.g. 'Azadpur Mandi'")
    interval_seconds: float = Field(10.0, gt=0)


class TrendOverrideRequest(BaseModel):
    drift_pct_per_day: float = Field(..., description="Positive = rising, negative = falling")


class ShockRequest(BaseModel):
    commodity: str
    market_name: str
    drift_pct_per_day: float = Field(40.0, description="Magnitude/direction of the price move")
    duration_seconds: float = Field(90.0, gt=0)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _get_generator_or_404(commodity: str, market_name: str):
    generator = market_feed_fleet.get(commodity, market_name)
    if generator is None:
        raise HTTPException(
            status_code=404,
            detail=f"No market feed registered for '{commodity}' at '{market_name}'",
        )
    return generator


def _registered_keys() -> List[Tuple[str, str]]:
    return list(market_feed_fleet._generators.keys())  # noqa: SLF001 -- same-package cooperation


# --------------------------------------------------------------------------
# Feed management
# --------------------------------------------------------------------------
@router.post("/feeds", status_code=201)
async def register_feed(payload: FeedRegisterRequest) -> dict:
    key = (payload.commodity.lower(), payload.market_name)
    if key in _feed_tasks and not _feed_tasks[key].done():
        raise HTTPException(status_code=409, detail=f"Feed for {key} is already running")

    try:
        generator = market_feed_fleet.register(payload.commodity, payload.market_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _feed_tasks[key] = asyncio.create_task(generator.stream(payload.interval_seconds))
    logger.info(f"[market_routes] started feed for {payload.commodity} @ {payload.market_name}")
    return {"commodity": payload.commodity.lower(), "market_name": payload.market_name, "status": "streaming"}


@router.get("/feeds")
async def list_feeds() -> List[dict]:
    feeds = []
    for commodity, market_name in _registered_keys():
        generator = market_feed_fleet.get(commodity, market_name)
        feeds.append({
            "commodity": commodity,
            "market_name": market_name,
            "state": generator.baseline.state if generator else None,
            "is_streaming": (commodity, market_name) in _feed_tasks
            and not _feed_tasks[(commodity, market_name)].done(),
        })
    return feeds


@router.delete("/feeds/{commodity}/{market_name}", status_code=200)
async def stop_feed(commodity: str, market_name: str) -> None:
    key = (commodity.lower(), market_name)
    generator = _get_generator_or_404(commodity, market_name)
    generator.stop()
    task = _feed_tasks.pop(key, None)
    if task is not None:
        task.cancel()
    logger.info(f"Stopped feed for {commodity} @ {market_name}")

    return {
        "status": "success",
        "message": f"Stopped feed for {commodity} at {market_name}"
    }


# --------------------------------------------------------------------------
# Prices
# --------------------------------------------------------------------------
@router.get("/prices")
async def list_latest_prices() -> List[dict]:
    prices = []
    for commodity, market_name in _registered_keys():
        latest = market_feed_fleet.get_latest_price(commodity, market_name)
        if latest is not None:
            prices.append(latest)
    return prices


@router.get("/prices/{commodity}/{market_name}")
async def get_latest_price(commodity: str, market_name: str) -> dict:
    _get_generator_or_404(commodity, market_name)
    latest = market_feed_fleet.get_latest_price(commodity, market_name)
    if latest is None:
        raise HTTPException(status_code=404, detail="Feed registered but no ticks generated yet")
    return latest


@router.get("/prices/{commodity}/{market_name}/history")
async def get_price_history(
    commodity: str, market_name: str, limit: int = Query(50, ge=1, le=500)
) -> List[dict]:
    _get_generator_or_404(commodity, market_name)
    return market_feed_fleet.get_price_history(commodity, market_name, limit=limit)


@router.post("/prices/{commodity}/{market_name}/trend")
async def set_price_trend(commodity: str, market_name: str, payload: TrendOverrideRequest) -> dict:
    generator = _get_generator_or_404(commodity, market_name)
    generator.set_trend(payload.drift_pct_per_day)
    return {
        "commodity": commodity.lower(),
        "market_name": market_name,
        "drift_pct_per_day": payload.drift_pct_per_day,
    }


# --------------------------------------------------------------------------
# Simulation / demo hooks
# --------------------------------------------------------------------------
@router.post("/simulate/shock")
async def simulate_shock(payload: ShockRequest) -> dict:
    try:
        event = await anomaly_injector.inject_market_shock(
            payload.commodity,
            payload.market_name,
            drift_pct_per_day=payload.drift_pct_per_day,
            duration_seconds=payload.duration_seconds,
        )
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return event.to_dict()


# --------------------------------------------------------------------------
# Recommendations (placeholder heuristic pending ai_models/price_forecaster.py)
# --------------------------------------------------------------------------
@router.get("/recommendations/{commodity}/{market_name}")
async def get_recommendation(commodity: str, market_name: str) -> dict:
    _get_generator_or_404(commodity, market_name)
    history = market_feed_fleet.get_price_history(commodity, market_name, limit=20)
    if len(history) < 2:
        return {
            "commodity": commodity.lower(),
            "market_name": market_name,
            "recommendation": "insufficient_data",
            "reason": "Not enough price history yet to form a recommendation",
        }

    recent_changes = [tick["change_pct"] for tick in history]
    avg_change = sum(recent_changes) / len(recent_changes)

    if avg_change > 1.0:
        recommendation, reason = "hold", "Prices have been trending up -- consider waiting to sell"
    elif avg_change < -1.0:
        recommendation, reason = "sell", "Prices have been trending down -- consider selling before further decline"
    else:
        recommendation, reason = "watch", "Prices are roughly stable"

    return {
        "commodity": commodity.lower(),
        "market_name": market_name,
        "recommendation": recommendation,
        "reason": reason,
        "avg_recent_change_pct": round(avg_change, 3),
        "note": "Placeholder heuristic -- will be superseded by ai_models/price_forecaster.py",
    }