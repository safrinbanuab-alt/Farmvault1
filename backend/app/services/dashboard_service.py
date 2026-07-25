"""
Dashboard service.

Aggregates data across Produce, Storage, Market, Prediction, and Alert
tables into the summary payloads consumed by Dashboard.jsx and
dashboard_routes.py.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.produce import Produce, ProduceStage
from app.models.storage import StorageUnit
from app.models.alert import Alert, AlertSeverity
from app.utils.logger import get_logger


logger = get_logger(__name__)


AT_RISK_DECAY_THRESHOLD = 60.0


_ACTIVE_STAGES = (
    ProduceStage.HARVESTED,
    ProduceStage.FRESH,
    ProduceStage.RIPENING,
    ProduceStage.PEAK,
    ProduceStage.DECAYING,
)


# ---------------------------------------------------------
# Dashboard Summary Cards
# ---------------------------------------------------------

async def get_dashboard_summary(
    db: AsyncSession
):

    total_batches = await db.scalar(
        select(func.count(Produce.id))
    ) or 0


    active_batches = await db.scalar(
        select(func.count(Produce.id))
        .where(
            Produce.current_stage.in_(_ACTIVE_STAGES)
        )
    ) or 0


    total_quantity = await db.scalar(
        select(
            func.coalesce(
                func.sum(Produce.quantity_kg),
                0
            )
        )
        .where(
            Produce.current_stage.in_(_ACTIVE_STAGES)
        )
    ) or 0


    total_value = await db.scalar(
        select(
            func.coalesce(
                func.sum(
                    Produce.current_estimated_value
                ),
                0
            )
        )
        .where(
            Produce.current_stage.in_(_ACTIVE_STAGES)
        )
    ) or 0


    risk_count = await db.scalar(
        select(func.count(Produce.id))
        .where(
            Produce.decay_percent >= AT_RISK_DECAY_THRESHOLD
        )
    ) or 0


    active_alerts = await db.scalar(
        select(func.count(Alert.id))
        .where(
            Alert.is_resolved.is_(False)
        )
    ) or 0


    critical_alerts = await db.scalar(
        select(func.count(Alert.id))
        .where(
            Alert.is_resolved.is_(False),
            Alert.severity == AlertSeverity.CRITICAL
        )
    ) or 0



    return {

        "total_batches": total_batches,

        "active_batches": active_batches,

        "total_quantity_kg": round(
            float(total_quantity),
            2
        ),

        "total_estimated_value": round(
            float(total_value),
            2
        ),

        "at_risk_batch_count": risk_count,

        "active_alerts_count": active_alerts,

        "critical_alerts_count": critical_alerts,

        "generated_at":
            datetime.now(timezone.utc).isoformat()
    }



# ---------------------------------------------------------
# Stage Chart
# ---------------------------------------------------------

async def get_stage_breakdown(
    db: AsyncSession
):

    result = await db.execute(

        select(
            Produce.current_stage,
            func.count(Produce.id)
        )
        .group_by(
            Produce.current_stage
        )

    )


    rows = result.all()


    return {

        (
            stage.value
            if hasattr(stage, "value")
            else str(stage)
        ):
        count

        for stage, count in rows
    }



# ---------------------------------------------------------
# Category Chart
# ---------------------------------------------------------

async def get_category_breakdown(
    db: AsyncSession
):

    result = await db.execute(

        select(
            Produce.category,
            func.count(Produce.id)
        )
        .group_by(
            Produce.category
        )

    )


    rows = result.all()


    return {

        (
            category.value
            if hasattr(category, "value")
            else str(category)
        ):
        count

        for category,count in rows

    }



# ---------------------------------------------------------
# Value At Risk
# ---------------------------------------------------------

async def get_value_at_risk(
    db: AsyncSession
):

    value = await db.scalar(

        select(
            func.coalesce(
                func.sum(
                    Produce.current_estimated_value
                ),
                0
            )
        )
        .where(
            Produce.decay_percent >= AT_RISK_DECAY_THRESHOLD
        )

    )


    return round(
        float(value or 0),
        2
    )



# ---------------------------------------------------------
# Risk Produce List
# ---------------------------------------------------------

async def get_top_at_risk_produce(
    db: AsyncSession,
    limit: int = 5
):

    result = await db.execute(

        select(Produce)

        .where(
            Produce.decay_percent >= AT_RISK_DECAY_THRESHOLD
        )

        .order_by(
            Produce.decay_percent.desc()
        )

        .limit(limit)

    )


    return result.scalars().all()



# ---------------------------------------------------------
# Alerts
# ---------------------------------------------------------

async def get_recent_alerts(
    db: AsyncSession,
    limit: int = 10
):

    result = await db.execute(

        select(Alert)

        .where(
            Alert.is_resolved.is_(False)
        )

        .order_by(
            Alert.triggered_at.desc()
        )

        .limit(limit)

    )


    return result.scalars().all()



# ---------------------------------------------------------
# Storage
# ---------------------------------------------------------

async def get_storage_utilization(
    db: AsyncSession
):

    result = await db.execute(

        select(StorageUnit)

        .where(
            StorageUnit.is_active.is_(True)
        )

    )


    units = result.scalars().all()


    output = []


    for unit in units:

        utilization = 0


        if unit.capacity_kg:

            utilization = round(

                (
                    unit.current_load_kg /
                    unit.capacity_kg
                )
                *
                100,

                1
            )



        output.append(

            {

                "storage_id": unit.id,

                "name": unit.name,

                "capacity_kg": unit.capacity_kg,

                "current_load_kg":
                    unit.current_load_kg,

                "utilization_pct":
                    utilization,

                "temperature":
                    unit.current_temperature_c,

                "humidity":
                    unit.current_humidity_pct
            }

        )


    return output



# ---------------------------------------------------------
# Activity Timeline
# ---------------------------------------------------------

async def get_recent_activity_window(
    db: AsyncSession,
    hours: float = 24
):

    since = (
        datetime.now(timezone.utc)
        -
        timedelta(hours=hours)
    )


    new_batches = await db.scalar(

        select(func.count(Produce.id))

        .where(
            Produce.created_at >= since
        )

    ) or 0



    new_alerts = await db.scalar(

        select(func.count(Alert.id))

        .where(
            Alert.triggered_at >= since
        )

    ) or 0



    return {

        "window_hours": hours,

        "new_batches": new_batches,

        "new_alerts": new_alerts

    }



# ---------------------------------------------------------
# Complete Dashboard Overview
# ---------------------------------------------------------

async def get_overview(
    db: AsyncSession
):

    risk_products = await get_top_at_risk_produce(db)


    alerts = await get_recent_alerts(db)


    return {


        "summary":
            await get_dashboard_summary(db),



        "stage_breakdown":
            await get_stage_breakdown(db),



        "category_breakdown":
            await get_category_breakdown(db),



        "top_at_risk_produce":

            [

                {
                    "id": p.id,
                    "name": p.name,
                    "decay_percent": p.decay_percent,
                    "stage": (
                        p.current_stage.value
                        if hasattr(
                            p.current_stage,
                            "value"
                        )
                        else str(p.current_stage)
                    )
                }

                for p in risk_products

            ],



        "recent_alerts":

            [

                {

                    "id": a.id,

                    "title": a.title,

                    "severity":
                        (
                            a.severity.value
                            if hasattr(
                                a.severity,
                                "value"
                            )
                            else str(a.severity)
                        )

                }

                for a in alerts

            ],



        "storage_utilization":
            await get_storage_utilization(db),



        "recent_activity":
            await get_recent_activity_window(db)

    }