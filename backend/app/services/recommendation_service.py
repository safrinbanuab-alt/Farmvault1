"""
Recommendation service.

Combines a produce batch's decay trajectory, its latest AI predictions, and
how its value compares to the live market to produce an actionable
recommendation (sell now / hold / relocate to better storage / discount &
liquidate). Powers RecommendationCard.jsx and raises Alerts for
urgent cases.

If ai_models.optimizer is available it is used as the primary decision
engine; otherwise a transparent rule-based heuristic is used so the service
still works before that module exists.
"""

from __future__ import annotations

import asyncio

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.produce import Produce, ProduceStage
from app.models.alert import (
    Alert,
    AlertType,
    AlertSeverity,
    AlertSource,
)
from app.models.prediction import (
    Prediction,
    PredictionType,
)

from app.services import market_service
from app.utils.logger import get_logger


logger = get_logger(__name__)


# ---------------------------------------------------------
# Optional AI Optimizer
# ---------------------------------------------------------

try:
    from app.ai_models.optimizer import (
        recommend_action as _ai_recommend_action
    )

except ImportError:
    _ai_recommend_action = None



# ---------------------------------------------------------
# Constants
# ---------------------------------------------------------

URGENT_ACTIONS = {
    "dispose",
    "apply_discount",
    "sell_now",
}



# ---------------------------------------------------------
# Prediction
# ---------------------------------------------------------

async def get_latest_prediction(
    db: AsyncSession,
    produce_id: str,
    prediction_type: PredictionType,
) -> Optional[Prediction]:

    result = await db.execute(
        select(Prediction)
        .where(
            Prediction.produce_id == produce_id
        )
        .where(
            Prediction.prediction_type == prediction_type
        )
        .order_by(
            Prediction.generated_at.desc()
        )
    )

    return result.scalars().first()



# ---------------------------------------------------------
# Generate Single Recommendation
# ---------------------------------------------------------

async def generate_recommendation(
    db: AsyncSession,
    produce_id: str,
) -> dict:


    result = await db.execute(
        select(Produce)
        .where(
            Produce.id == produce_id
        )
    )

    produce = result.scalars().first()


    if produce is None:

        raise ValueError(
            f"Produce {produce_id} not found"
        )



    # Already finished batch

    if produce.current_stage in (
        ProduceStage.SOLD,
        ProduceStage.DISPOSED,
    ):

        return {

            "produce_id": produce_id,

            "action": "monitor",

            "confidence": 1.0,

            "reasoning":
                "Batch already completed.",

            "generated_at":
                datetime.now(timezone.utc).isoformat()
        }



    # Market comparison

    market_comparison = await (
        market_service.compare_produce_to_market(
            db,
            produce
        )
    )



    # Predictions

    decay_prediction = await get_latest_prediction(
        db,
        produce_id,
        PredictionType.DECAY
    )


    price_prediction = await get_latest_prediction(
        db,
        produce_id,
        PredictionType.PRICE
    )



    # -----------------------------------------------------
    # AI Recommendation
    # -----------------------------------------------------

    if _ai_recommend_action:

        try:

            recommendation = await asyncio.to_thread(
                _ai_recommend_action,
                produce=produce,
                market_comparison=market_comparison,
                decay_prediction=decay_prediction,
                price_prediction=price_prediction,
            )


            recommendation.setdefault(
                "produce_id",
                produce_id
            )


            await _maybe_raise_alert(
                db,
                produce,
                recommendation
            )


            return recommendation



        except Exception:

            logger.exception(
                "AI recommendation failed. Using heuristic."
            )



    # -----------------------------------------------------
    # Fallback Heuristic
    # -----------------------------------------------------

    recommendation = _heuristic_recommendation(
        produce,
        market_comparison,
        decay_prediction,
    )


    await _maybe_raise_alert(
        db,
        produce,
        recommendation
    )


    return recommendation





# ---------------------------------------------------------
# Heuristic Logic
# ---------------------------------------------------------

def _heuristic_recommendation(
    produce: Produce,
    market_comparison,
    decay_prediction: Optional[Prediction],
) -> dict:


    decay = produce.decay_percent or 0.0


    projected_decay = decay


    if (
        decay_prediction
        and decay_prediction.predicted_value is not None
    ):

        projected_decay = max(
            decay,
            decay_prediction.predicted_value
        )



    if projected_decay >= 90:

        action = "dispose"
        confidence = 0.90
        reason = (
            "Critical spoilage risk detected."
        )


    elif projected_decay >= 70:

        action = "apply_discount"
        confidence = 0.75
        reason = (
            "High decay detected. "
            "Discount selling recommended."
        )


    elif (
        market_comparison.recommendation
        == "sell_now"
    ):

        action = "sell_now"
        confidence = 0.70
        reason = (
            "Market opportunity detected."
        )


    elif decay >= 40:

        action = "move_to_cold_storage"
        confidence = 0.60
        reason = (
            "Cold storage can slow degradation."
        )


    elif (
        market_comparison.recommendation
        == "hold"
    ):

        action = "hold"
        confidence = 0.65
        reason = (
            "Current market value is favorable."
        )


    else:

        action = "monitor"
        confidence = 0.50
        reason = (
            "No urgent action required."
        )



    return {

        "produce_id":
            produce.id,

        "action":
            action,

        "confidence":
            confidence,

        "reasoning":
            reason,

        "market_price_per_kg":
            market_comparison.market_price_per_kg,

        "estimated_value_per_kg":
            market_comparison.produce_estimated_value_per_kg,

        "generated_at":
            datetime.now(timezone.utc).isoformat()
    }





# ---------------------------------------------------------
# Bulk Recommendation
# ---------------------------------------------------------

async def generate_recommendations_bulk(
    db: AsyncSession,
    produce_ids: list[str],
) -> list[dict]:


    results = []


    for produce_id in produce_ids:

        result = await generate_recommendation(
            db,
            produce_id
        )

        results.append(result)


    return results





# ---------------------------------------------------------
# Alert Handling
# ---------------------------------------------------------

async def _maybe_raise_alert(
    db: AsyncSession,
    produce: Produce,
    recommendation: dict,
):


    action = recommendation.get(
        "action"
    )


    if action not in URGENT_ACTIONS:

        return None



    result = await db.execute(

        select(Alert)

        .where(
            Alert.produce_id == produce.id
        )

        .where(
            Alert.alert_type
            == AlertType.RECOMMENDED_ACTION
        )

        .where(
            Alert.is_resolved.is_(False)
        )

    )


    existing = result.scalars().first()



    severity = (

        AlertSeverity.CRITICAL

        if action == "dispose"

        else AlertSeverity.HIGH

    )



    if existing:


        existing.message = (
            recommendation.get(
                "reasoning",
                ""
            )
        )


        existing.severity = severity


        existing.extra_data = dict(
            recommendation
        )


        await db.commit()

        await db.refresh(existing)


        return existing





    alert = Alert(

        produce_id =
            produce.id,


        alert_type =
            AlertType.RECOMMENDED_ACTION,


        severity =
            severity,


        source =
            AlertSource.RECOMMENDATION_ENGINE,


        title =
            f"Recommended action: {action.replace('_',' ')}",


        message =
            recommendation.get(
                "reasoning",
                ""
            ),


        extra_data =
            dict(recommendation)

    )



    db.add(alert)


    await db.commit()


    await db.refresh(alert)


    logger.info(
        "Recommendation alert created for %s",
        produce.id
    )


    return alert