from fastapi import APIRouter

from app.utils.logger import get_logger


logger = get_logger(__name__)

router = APIRouter()


# =========================================================
# Complete Dashboard Overview (Demo Data)
# =========================================================

@router.get("/overview", tags=["Dashboard"])
async def get_dashboard_overview():

    return {

        "summary": {
            "total_batches": 120,
            "active_batches": 95,
            "total_quantity_kg": 8500,
            "total_estimated_value": 450000,
            "at_risk_batch_count": 12,
            "active_alerts_count": 5,
            "critical_alerts_count": 2,
            "generated_at": "2026-07-25T22:00:00"
        },


        "stage_breakdown": {
            "HARVESTED": 35,
            "FRESH": 40,
            "RIPENING": 25,
            "PEAK": 15,
            "DECAYING": 5
        },


        "category_breakdown": {
            "FRUIT": 60,
            "VEGETABLE": 40,
            "GRAIN": 20
        },


        "top_at_risk_produce": [

            {
                "id": 1,
                "name": "Tomato",
                "decay_percent": 82,
                "stage": "DECAYING"
            },

            {
                "id": 2,
                "name": "Mango",
                "decay_percent": 70,
                "stage": "RIPENING"
            }

        ],


        "recent_alerts": [

            {
                "id": 1,
                "title": "High Storage Temperature",
                "severity": "CRITICAL",
                "type": "STORAGE",
                "triggered_at": "2026-07-25T21:30:00"
            },

            {
                "id": 2,
                "title": "Decay Risk Increased",
                "severity": "WARNING",
                "type": "PRODUCE",
                "triggered_at": "2026-07-25T21:45:00"
            }

        ],


        "storage_utilization": [

            {
                "storage_id": 1,
                "name": "Cold Storage A",
                "capacity_kg": 10000,
                "current_load_kg": 8200,
                "utilization_pct": 82,
                "temperature": 4,
                "humidity": 75
            },

            {
                "storage_id": 2,
                "name": "Warehouse B",
                "capacity_kg": 15000,
                "current_load_kg": 9000,
                "utilization_pct": 60,
                "temperature": 8,
                "humidity": 65
            }

        ],


        "recent_activity": {

            "window_hours": 24,
            "new_batches": 8,
            "new_alerts": 3

        }

    }



# =========================================================
# Summary
# =========================================================

@router.get("/summary", tags=["Dashboard"])
async def dashboard_summary():

    data = await get_dashboard_overview()

    return data["summary"]



# =========================================================
# Stage Breakdown
# =========================================================

@router.get("/stage-breakdown", tags=["Dashboard"])
async def dashboard_stage_breakdown():

    data = await get_dashboard_overview()

    return data["stage_breakdown"]



# =========================================================
# Category Breakdown
# =========================================================

@router.get("/category-breakdown", tags=["Dashboard"])
async def dashboard_category_breakdown():

    data = await get_dashboard_overview()

    return data["category_breakdown"]



# =========================================================
# Risk Produce
# =========================================================

@router.get("/risk", tags=["Dashboard"])
async def dashboard_risk():

    data = await get_dashboard_overview()

    return data["top_at_risk_produce"]



# =========================================================
# Alerts
# =========================================================

@router.get("/alerts", tags=["Dashboard"])
async def dashboard_alerts():

    data = await get_dashboard_overview()

    return data["recent_alerts"]



# =========================================================
# Storage
# =========================================================

@router.get("/storage", tags=["Dashboard"])
async def dashboard_storage():

    data = await get_dashboard_overview()

    return data["storage_utilization"]



# =========================================================
# Activity
# =========================================================

@router.get("/activity", tags=["Dashboard"])
async def dashboard_activity():

    data = await get_dashboard_overview()

    return data["recent_activity"]