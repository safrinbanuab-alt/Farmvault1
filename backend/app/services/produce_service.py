from __future__ import annotations

from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.produce import Produce, ProduceStage
from app.models.storage import StorageUnit

from app.schemas.produce_schema import (
    ProduceCreate,
    ProduceUpdate,
    ProduceDecayUpdate,
)

from app.utils.logger import get_logger


logger = get_logger(__name__)


class ProduceNotFoundError(Exception):
    pass


class StorageCapacityExceededError(Exception):
    pass



# =========================================================
# CREATE
# =========================================================


async def create_produce(
    db: AsyncSession,
    payload: ProduceCreate
) -> Produce:


    if payload.storage_id:

        await _assert_storage_has_capacity(
            db,
            payload.storage_id,
            payload.quantity_kg
        )


    produce = Produce(

        name=payload.name,

        variety=payload.variety,

        category=payload.category,

        batch_code=payload.batch_code,

        quantity_kg=payload.quantity_kg,

        initial_quantity_kg=payload.quantity_kg,

        unit=payload.unit,

        farmer_name=payload.farmer_name,

        farm_location=payload.farm_location,

        harvest_date=payload.harvest_date,

        initial_price_per_kg=payload.initial_price_per_kg,

        storage_id=payload.storage_id,

        quality_grade=payload.quality_grade,

        moisture_content=payload.moisture_content,

        current_stage=ProduceStage.HARVESTED,

        decay_percent=0.0,

        days_since_harvest=0.0,

        current_estimated_value=(

            payload.initial_price_per_kg *
            payload.quantity_kg

            if payload.initial_price_per_kg

            else None
        ),

        is_simulated=payload.is_simulated,

        notes=payload.notes,
    )


    db.add(produce)


    if payload.storage_id:

        await _increment_storage_load(
            db,
            payload.storage_id,
            payload.quantity_kg
        )


    await db.commit()

    await db.refresh(produce)


    logger.info(
        "Created produce %s",
        produce.id
    )


    return produce





# =========================================================
# READ
# =========================================================


async def get_produce(
    db: AsyncSession,
    produce_id: str
) -> Optional[Produce]:


    result = await db.execute(

        select(Produce)
        .where(
            Produce.id == produce_id
        )

    )


    return result.scalars().first()



async def get_produce_or_404(
    db: AsyncSession,
    produce_id:str
):

    produce = await get_produce(
        db,
        produce_id
    )


    if not produce:

        raise ProduceNotFoundError(
            f"Produce {produce_id} not found"
        )


    return produce





async def list_produce(
    db: AsyncSession,
    skip:int=0,
    limit:int=50,
    category=None,
    stage=None,
    storage_id=None
):


    query = select(Produce)


    if category:

        query=query.where(
            Produce.category==category
        )


    if stage:

        query=query.where(
            Produce.current_stage==stage
        )


    if storage_id:

        query=query.where(
            Produce.storage_id==storage_id
        )



    count_result = await db.execute(

        select(
            func.count(Produce.id)
        )
        .select_from(Produce)

    )


    total = count_result.scalar() or 0



    result = await db.execute(

        query
        .order_by(
            Produce.updated_at.desc()
        )
        .offset(skip)
        .limit(limit)

    )


    return total, result.scalars().all()





async def list_at_risk_produce(
    db:AsyncSession,
    decay_threshold:float=60,
    limit:int=10
):


    result = await db.execute(

        select(Produce)
        .where(
            Produce.decay_percent >= decay_threshold
        )
        .where(
            Produce.current_stage.notin_(
                [
                    ProduceStage.SOLD,
                    ProduceStage.DISPOSED
                ]
            )
        )
        .order_by(
            Produce.decay_percent.desc()
        )
        .limit(limit)

    )


    return result.scalars().all()





# =========================================================
# UPDATE
# =========================================================


async def update_produce(
    db:AsyncSession,
    produce_id:str,
    payload:ProduceUpdate
):


    produce = await get_produce_or_404(
        db,
        produce_id
    )


    data = payload.model_dump(
        exclude_unset=True
    )


    new_storage=data.get(
        "storage_id"
    )


    if new_storage and new_storage != produce.storage_id:


        await _move_produce_storage(
            db,
            produce,
            new_storage
        )


        data.pop(
            "storage_id",
            None
        )



    for key,value in data.items():

        setattr(
            produce,
            key,
            value
        )



    await db.commit()

    await db.refresh(produce)


    return produce





async def apply_decay_update(
    db:AsyncSession,
    produce_id:str,
    payload:ProduceDecayUpdate
):


    produce = await get_produce_or_404(
        db,
        produce_id
    )


    produce.decay_percent = payload.decay_percent

    produce.current_stage = payload.current_stage

    produce.days_since_harvest = payload.days_since_harvest



    if payload.shelf_life_days_estimate:

        produce.shelf_life_days_estimate = (
            payload.shelf_life_days_estimate
        )


    if payload.moisture_content:

        produce.moisture_content = (
            payload.moisture_content
        )



    if produce.current_stage in (

        ProduceStage.SPOILED,

        ProduceStage.DISPOSED

    ):

        produce.current_estimated_value=0



    await db.commit()

    await db.refresh(produce)


    return produce





async def update_estimated_value(
    db:AsyncSession,
    produce_id:str,
    price_per_kg:float
):


    produce = await get_produce_or_404(
        db,
        produce_id
    )


    factor=max(
        0,
        1-(produce.decay_percent/100)
    )


    produce.current_estimated_value=round(
        price_per_kg *
        produce.quantity_kg *
        factor,
        2
    )


    await db.commit()

    await db.refresh(produce)


    return produce





# =========================================================
# STORAGE
# =========================================================


async def assign_storage(
    db:AsyncSession,
    produce_id:str,
    storage_id:str
):


    produce=await get_produce_or_404(
        db,
        produce_id
    )


    await _move_produce_storage(
        db,
        produce,
        storage_id
    )


    await db.commit()

    await db.refresh(produce)


    return produce






async def mark_sold(
    db:AsyncSession,
    produce_id:str
):


    produce=await get_produce_or_404(
        db,
        produce_id
    )


    produce.current_stage=ProduceStage.SOLD


    await _release_storage_load(
        db,
        produce
    )


    await db.commit()

    await db.refresh(produce)


    return produce






async def mark_disposed(
    db:AsyncSession,
    produce_id:str,
    reason:str|None=None
):


    produce=await get_produce_or_404(
        db,
        produce_id
    )


    produce.current_stage=ProduceStage.DISPOSED

    produce.current_estimated_value=0



    await _release_storage_load(
        db,
        produce
    )


    await db.commit()

    await db.refresh(produce)


    return produce






async def delete_produce(
    db:AsyncSession,
    produce_id:str
):


    produce=await get_produce(
        db,
        produce_id
    )


    if not produce:

        return False



    await _release_storage_load(
        db,
        produce
    )


    await db.delete(produce)

    await db.commit()


    return True





# =========================================================
# HELPERS
# =========================================================


async def _assert_storage_has_capacity(
    db,
    storage_id,
    quantity
):


    result=await db.execute(

        select(StorageUnit)
        .where(
            StorageUnit.id==storage_id
        )

    )


    storage=result.scalars().first()


    if not storage:

        raise ProduceNotFoundError(
            "Storage not found"
        )


    if (
        storage.current_load_kg +
        quantity
        >
        storage.capacity_kg
    ):

        raise StorageCapacityExceededError(
            "Storage capacity exceeded"
        )


    return storage





async def _increment_storage_load(
    db,
    storage_id,
    quantity
):


    result=await db.execute(

        select(StorageUnit)
        .where(
            StorageUnit.id==storage_id
        )

    )


    storage=result.scalars().first()


    if storage:

        storage.current_load_kg += quantity






async def _release_storage_load(
    db,
    produce
):


    if not produce.storage_id:

        return



    result=await db.execute(

        select(StorageUnit)
        .where(
            StorageUnit.id==produce.storage_id
        )

    )


    storage=result.scalars().first()


    if storage:

        storage.current_load_kg=max(

            0,

            storage.current_load_kg -
            produce.quantity_kg

        )


    produce.storage_id=None





async def _move_produce_storage(
    db,
    produce,
    new_storage_id
):


    await _assert_storage_has_capacity(
        db,
        new_storage_id,
        produce.quantity_kg
    )


    await _release_storage_load(
        db,
        produce
    )


    produce.storage_id=new_storage_id


    await _increment_storage_load(
        db,
        new_storage_id,
        produce.quantity_kg
    )