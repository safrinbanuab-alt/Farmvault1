"""
Simulation service.

Orchestrates "what-if" scenario runs (twin_core/scenario_engine.py),
advances the simulation clock for a produce batch, and triggers anomaly
injection via iot_simulator/anomaly_injector.py. Powers
ScenarioAnalysis.jsx, ScenarioComparator.jsx, and InjectAnomalyButton.jsx.

Like recommendation_service.py, this degrades gracefully to a local
heuristic projection when twin_core/iot_simulator modules aren't available
yet, so the API contract is stable from day one.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


from app.models.produce import (
    Produce,
    ProduceStage,
    QualityGrade,
)

from app.models.storage import (
    StorageUnit,
    StorageReading,
)

from app.models.alert import (
    Alert,
    AlertType,
    AlertSeverity,
    AlertSource,
)


from app.schemas.twin_schema import (
    ScenarioRequest,
    ScenarioResult,
    ScenarioProjectedPoint,
)


from app.services import (
    market_service,
    produce_service,
)


from app.utils.logger import get_logger


logger = get_logger(__name__)



try:
    from app.twin_core.scenario_engine import (
        run_scenario as _engine_run_scenario
    )
except ImportError:
    _engine_run_scenario = None



try:
    from app.iot_simulator.anomaly_injector import (
        inject as _inject_anomaly_event
    )
except ImportError:
    _inject_anomaly_event = None




_SIMULATION_TICKS: dict[str,int] = {}



# =========================================================
# Scenario Simulation
# =========================================================


async def run_scenario(
    db: AsyncSession,
    request: ScenarioRequest
) -> ScenarioResult:


    result = await db.execute(

        select(Produce)
        .where(
            Produce.id == request.produce_id
        )

    )


    produce = result.scalars().first()



    if produce is None:

        raise ValueError(
            f"Produce {request.produce_id} not found"
        )



    storage = None


    if produce.storage_id:


        storage_result = await db.execute(

            select(StorageUnit)
            .where(
                StorageUnit.id ==
                produce.storage_id
            )

        )


        storage = storage_result.scalars().first()



    market_price = await (
        market_service.get_current_price_per_kg(
            db,
            produce.name
        )
    )


    if market_price is None:

        market_price = (
            produce.initial_price_per_kg
            or 0.0
        )



    if _engine_run_scenario:

        try:

            return _engine_run_scenario(

                produce=produce,

                storage=storage,

                parameters=request.parameters,

                market_price_per_kg=market_price,

                scenario_name=request.scenario_name

            )


        except Exception:

            logger.exception(
                "Scenario engine failed"
            )



    return _heuristic_scenario(

        produce,
        storage,
        request,
        market_price

    )




# =========================================================
# Scenario Engine
# =========================================================


def _heuristic_scenario(
    produce: Produce,
    storage: Optional[StorageUnit],
    request: ScenarioRequest,
    market_price_per_kg: float,
):


    params = request.parameters


    days = int(
        params.days_to_simulate
    )



    decay_rate = 3.0



    temperature = (
        params.temperature_override_c
    )



    if temperature is None and storage:

        temperature = (
            storage.current_temperature_c
        )



    if (
        temperature
        and storage
        and storage.ideal_temp_max_c
        and temperature >
        storage.ideal_temp_max_c
    ):

        decay_rate += (
            temperature -
            storage.ideal_temp_max_c
        ) * 0.5




    baseline=[]

    projection=[]



    initial_decay = (
        produce.decay_percent
        or 0
    )



    for day in range(days+1):


        base_decay=min(
            100,
            initial_decay +
            (3*day)
        )


        baseline.append(

            ScenarioProjectedPoint(

                day=day,

                projected_decay_percent=
                    round(base_decay,2),

                projected_quality_grade=
                    _grade_for_decay(
                        base_decay
                    ),

                projected_stage=
                    _stage_for_decay(
                        base_decay
                    ),

                projected_price_per_kg=
                    market_price_per_kg,

                projected_value=
                    _calculate_value(
                        produce,
                        base_decay,
                        market_price_per_kg
                    )

            )

        )




        scenario_decay=min(

            100,

            initial_decay +
            (
                decay_rate *
                day
            )

        )



        projection.append(

            ScenarioProjectedPoint(

                day=day,

                projected_decay_percent=
                    round(
                        scenario_decay,
                        2
                    ),

                projected_quality_grade=
                    _grade_for_decay(
                        scenario_decay
                    ),

                projected_stage=
                    _stage_for_decay(
                        scenario_decay
                    ),

                projected_price_per_kg=
                    market_price_per_kg,

                projected_value=
                    _calculate_value(
                        produce,
                        scenario_decay,
                        market_price_per_kg
                    )

            )

        )



    return ScenarioResult(

        scenario_name=
            request.scenario_name,

        produce_id=
            produce.id,

        baseline_final_value=
            baseline[-1].projected_value,

        scenario_final_value=
            projection[-1].projected_value,

        value_delta=
            round(

                projection[-1].projected_value
                -
                baseline[-1].projected_value,

                2
            ),

        projection=projection,

        recommendation=
            "Recommended"
    )




def _grade_for_decay(
    decay:float
):

    if decay < 20:
        return QualityGrade.A

    if decay < 50:
        return QualityGrade.B

    if decay < 80:
        return QualityGrade.C

    return QualityGrade.REJECTED





def _stage_for_decay(
    decay:float
):

    if decay >=95:
        return ProduceStage.SPOILED

    if decay >=70:
        return ProduceStage.DECAYING

    if decay >=40:
        return ProduceStage.PEAK

    return ProduceStage.FRESH





def _calculate_value(
    produce,
    decay,
    price
):

    if price is None:
        return None


    factor=max(
        0,
        1-(decay/100)
    )


    return round(
        price *
        produce.quantity_kg *
        factor,
        2
    )





# =========================================================
# Simulation Tick
# =========================================================


async def advance_tick(
    db: AsyncSession,
    produce_id:str
):


    _SIMULATION_TICKS[produce_id] = (
        _SIMULATION_TICKS.get(
            produce_id,
            0
        )
        +1
    )



    produce = await (
        produce_service.get_produce_or_404(
            db,
            produce_id
        )
    )



    storage=None



    if produce.storage_id:


        result=await db.execute(

            select(StorageUnit)
            .where(
                StorageUnit.id ==
                produce.storage_id
            )

        )


        storage=result.scalars().first()



    daily_decay=3.0



    if (
        storage
        and storage.current_temperature_c
        and storage.ideal_temp_max_c
        and
        storage.current_temperature_c >
        storage.ideal_temp_max_c
    ):

        daily_decay += (

            storage.current_temperature_c
            -
            storage.ideal_temp_max_c

        )*0.5



    new_decay=min(

        100,

        (
            produce.decay_percent
            or 0
        )
        +
        daily_decay

    )



    from app.schemas.produce_schema import ProduceDecayUpdate



    payload=ProduceDecayUpdate(

        decay_percent=
            round(new_decay,2),

        current_stage=
            _stage_for_decay(
                new_decay
            ),

        days_since_harvest=
            (
                produce.days_since_harvest
                or 0
            )
            +1,

        shelf_life_days_estimate=
            produce.shelf_life_days_estimate,

        moisture_content=
            produce.moisture_content

    )



    return await (
        produce_service.apply_decay_update(
            db,
            produce_id,
            payload
        )
    )





def reset_simulation(
    produce_id:str
):

    _SIMULATION_TICKS.pop(
        produce_id,
        None
    )




def get_tick_count(
    produce_id:str
):

    return _SIMULATION_TICKS.get(
        produce_id,
        0
    )





# =========================================================
# Anomaly Injection
# =========================================================


async def inject_anomaly(
    db:AsyncSession,
    storage_id:str,
    anomaly_type:str="temperature_spike"
):


    result=await db.execute(

        select(StorageUnit)
        .where(
            StorageUnit.id ==
            storage_id
        )

    )


    storage=result.scalars().first()



    if storage is None:

        raise ValueError(
            "Storage not found"
        )



    if _inject_anomaly_event:


        try:

            reading_data = _inject_anomaly_event(

                storage=storage,

                anomaly_type=anomaly_type

            )


        except Exception:

            reading_data = (
                _fallback_anomaly_reading(
                    storage,
                    anomaly_type
                )
            )


    else:

        reading_data = (
            _fallback_anomaly_reading(
                storage,
                anomaly_type
            )
        )



    reading=StorageReading(

        storage_id=storage.id,

        temperature_c=
            reading_data.get(
                "temperature_c"
            ),

        humidity_pct=
            reading_data.get(
                "humidity_pct"
            ),

        is_anomalous=True,

        anomaly_reason=
            reading_data.get(
                "reason"
            )

    )



    db.add(reading)



    alert=Alert(

        storage_id=storage.id,

        alert_type=
            _alert_type_for_anomaly(
                anomaly_type
            ),

        severity=
            AlertSeverity.HIGH,

        source=
            AlertSource.IOT_SIMULATOR,

        title=
            f"Anomaly: {anomaly_type}",

        message=
            reading_data.get(
                "reason"
            ),

        extra_data=
            reading_data

    )


    db.add(alert)


    await db.commit()


    await db.refresh(alert)



    return alert





def _fallback_anomaly_reading(
    storage,
    anomaly_type
):

    temp = (
        storage.current_temperature_c
        or 20
    )


    humidity = (
        storage.current_humidity_pct
        or 50
    )



    if anomaly_type=="temperature_spike":

        return {

            "temperature_c":
                temp+10,

            "humidity_pct":
                humidity,

            "reason":
                "Cooling failure detected"

        }



    return {

        "temperature_c":
            temp,

        "humidity_pct":
            humidity+20,

        "reason":
            "Humidity anomaly detected"

    }





def _alert_type_for_anomaly(
    anomaly_type
):

    return {

        "temperature_spike":
            AlertType.TEMPERATURE_BREACH,

        "humidity_spike":
            AlertType.HUMIDITY_BREACH

    }.get(

        anomaly_type,

        AlertType.ANOMALY_DETECTED

    )