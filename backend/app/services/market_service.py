from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import MandiPrice, MarketSnapshot
from app.models.produce import Produce

from app.schemas.market_schema import (
    MandiPriceCreate,
    MarketSnapshotCreate,
    MarketTrendPoint,
    MarketTrendResponse,
    ProduceMarketComparison,
)

from app.utils.logger import get_logger


logger = get_logger(__name__)


# =========================================================
# Mandi Price
# =========================================================


async def create_mandi_price(
    db: AsyncSession,
    payload: MandiPriceCreate
) -> MandiPrice:

    record = MandiPrice(
        **payload.model_dump()
    )

    db.add(record)

    await db.commit()
    await db.refresh(record)

    return record



async def bulk_import_mandi_prices(
    db: AsyncSession,
    rows: list[MandiPriceCreate]
) -> int:

    objects = [
        MandiPrice(**row.model_dump())
        for row in rows
    ]

    db.add_all(objects)

    await db.commit()

    logger.info(
        "Imported %d mandi price records",
        len(objects)
    )

    return len(objects)



async def get_latest_mandi_price(
    db: AsyncSession,
    commodity_name: str,
    mandi_name: Optional[str] = None
) -> Optional[MandiPrice]:

    query = (
        select(MandiPrice)
        .where(
            MandiPrice.commodity_name.ilike(
                commodity_name
            )
        )
    )


    if mandi_name:

        query = query.where(
            MandiPrice.mandi_name.ilike(
                mandi_name
            )
        )


    query = query.order_by(
        MandiPrice.price_date.desc()
    )


    result = await db.execute(query)

    return result.scalars().first()



async def list_mandi_prices(
    db: AsyncSession,
    commodity_name: Optional[str] = None,
    skip: int = 0,
    limit: int = 50
):

    count_query = select(
        func.count(MandiPrice.id)
    )


    query = select(MandiPrice)



    if commodity_name:

        condition = (
            MandiPrice.commodity_name.ilike(
                commodity_name
            )
        )

        count_query = count_query.where(
            condition
        )

        query = query.where(
            condition
        )


    total = await db.scalar(
        count_query
    ) or 0



    result = await db.execute(

        query
        .order_by(
            MandiPrice.price_date.desc()
        )
        .offset(skip)
        .limit(limit)

    )


    items = result.scalars().all()


    return total, items



# =========================================================
# Market Snapshot
# =========================================================


async def record_market_snapshot(
    db: AsyncSession,
    payload: MarketSnapshotCreate
) -> MarketSnapshot:


    snapshot = MarketSnapshot(
        **payload.model_dump()
    )


    db.add(snapshot)

    await db.commit()
    await db.refresh(snapshot)


    return snapshot



async def get_latest_snapshot(
    db: AsyncSession,
    commodity_name: str
) -> Optional[MarketSnapshot]:


    result = await db.execute(

        select(MarketSnapshot)
        .where(
            MarketSnapshot.commodity_name.ilike(
                commodity_name
            )
        )
        .order_by(
            MarketSnapshot.recorded_at.desc()
        )

    )


    return result.scalars().first()



async def get_current_price_per_kg(
    db: AsyncSession,
    commodity_name: str
) -> Optional[float]:


    snapshot = await get_latest_snapshot(
        db,
        commodity_name
    )


    if snapshot:

        return snapshot.price_per_kg



    mandi_price = await get_latest_mandi_price(
        db,
        commodity_name
    )



    if (
        mandi_price
        and mandi_price.modal_price
    ):

        divisor = (

            100.0
            if mandi_price.unit.value == "per_quintal"
            else 1.0

        )


        return round(
            mandi_price.modal_price / divisor,
            2
        )


    return None



# =========================================================
# Market Trend
# =========================================================


async def get_market_trend(
    db: AsyncSession,
    commodity_name: str,
    hours: float = 24
) -> MarketTrendResponse:


    since = (
        datetime.now(timezone.utc)
        -
        timedelta(hours=hours)
    )


    result = await db.execute(

        select(MarketSnapshot)
        .where(
            MarketSnapshot.commodity_name.ilike(
                commodity_name
            )
        )
        .where(
            MarketSnapshot.recorded_at >= since
        )
        .order_by(
            MarketSnapshot.recorded_at.asc()
        )

    )


    snapshots = result.scalars().all()



    points = [

        MarketTrendPoint(
            timestamp=s.recorded_at,
            price_per_kg=s.price_per_kg
        )

        for s in snapshots

    ]



    current_price = (

        points[-1].price_per_kg
        if points
        else None

    )



    change_pct_24h = None



    if (
        len(points) >= 2
        and points[0].price_per_kg
    ):

        change_pct_24h = round(

            (
                (
                    points[-1].price_per_kg
                    -
                    points[0].price_per_kg
                )
                /
                points[0].price_per_kg
            )
            *
            100,

            2

        )



    return MarketTrendResponse(

        commodity_name=commodity_name,

        points=points,

        current_price_per_kg=current_price,

        change_pct_24h=change_pct_24h

    )



# =========================================================
# Produce vs Market Comparison
# =========================================================


async def compare_produce_to_market(
    db: AsyncSession,
    produce: Produce
) -> ProduceMarketComparison:


    market_price = await get_current_price_per_kg(
        db,
        produce.name
    )


    produce_value_per_kg = None



    if (
        produce.current_estimated_value
        and produce.quantity_kg
    ):

        produce_value_per_kg = round(

            produce.current_estimated_value
            /
            produce.quantity_kg,

            2

        )



    variance_pct = None

    recommendation = None



    if (
        market_price
        and produce_value_per_kg is not None
    ):


        variance_pct = round(

            (
                (
                    produce_value_per_kg
                    -
                    market_price
                )
                /
                market_price
            )
            *
            100,

            2

        )



        if variance_pct <= -15:

            recommendation = "sell_now"


        elif variance_pct >= 15:

            recommendation = "hold"


        else:

            recommendation = "monitor"




    return ProduceMarketComparison(

        produce_id=produce.id,

        commodity_name=produce.name,

        produce_estimated_value_per_kg=
            produce_value_per_kg,

        market_price_per_kg=
            market_price,

        variance_pct=
            variance_pct,

        recommendation=
            recommendation

    )