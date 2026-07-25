"""
FarmVault FastAPI application entrypoint.

Wires up middleware, routers, lifespan startup/shutdown hooks (database
init, IoT simulator, WebSocket manager), and global exception handling.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


from app.api import (
    dashboard_routes,
    market_routes,
    patient_routes,
    prediction_routes,
    simulation_routes,
    twin_routes,
)

from app.config import settings
from app.database import (
    close_db,
    init_db,
)

from app.iot_simulator.event_bus import event_bus
from app.websocket.manager import ws_manager

from app.utils.logger import get_logger


logger = get_logger(__name__)




# =========================================================
# Application Lifespan
# =========================================================

@asynccontextmanager
async def lifespan(
    app: FastAPI
) -> AsyncGenerator[None, None]:

    logger.info(
        f"Starting {settings.app_name} "
        f"in '{settings.app_env}' mode..."
    )


    # -----------------------------------------
    # Database startup
    # SYNC SQLAlchemy
    # -----------------------------------------

    try:

        init_db()

        logger.info(
            "Database initialized successfully."
        )


    except Exception:

        logger.exception(
            "Database initialization failed"
        )

        raise



    # -----------------------------------------
    # Background Services
    # -----------------------------------------

    try:

        await event_bus.start()

        logger.info(
            "IoT event bus started."
        )


    except Exception:

        logger.exception(
            "Event bus startup failed"
        )

        raise



    yield



    # -----------------------------------------
    # Shutdown
    # -----------------------------------------

    logger.info(
        "Shutting down application..."
    )


    try:

        await event_bus.stop()

        logger.info(
            "IoT event bus stopped."
        )


    except Exception:

        logger.exception(
            "Event bus shutdown failed"
        )



    try:

        await ws_manager.disconnect_all()

        logger.info(
            "Websocket connections closed."
        )


    except Exception:

        logger.exception(
            "Websocket shutdown failed"
        )



    try:

        close_db()

        logger.info(
            "Database connection closed."
        )


    except Exception:

        logger.exception(
            "Database close failed"
        )



    logger.info(
        f"{settings.app_name} shut down cleanly."
    )





# =========================================================
# FastAPI App Factory
# =========================================================


def create_app() -> FastAPI:


    app = FastAPI(

        title=settings.app_name,

        description=(
            "AI-powered digital twin platform "
            "for post-harvest agricultural produce."
        ),

        version="1.0.0",

        docs_url=(
            "/docs"
            if not settings.is_production
            else None
        ),

        redoc_url=(
            "/redoc"
            if not settings.is_production
            else None
        ),

        lifespan=lifespan,

    )



    # =====================================================
    # CORS
    # =====================================================

    app.add_middleware(

        CORSMiddleware,

        allow_origins=settings.cors_origins,

        allow_credentials=True,

        allow_methods=["*"],

        allow_headers=["*"],

    )




    # =====================================================
    # Global Exception Handler
    # =====================================================

    @app.exception_handler(Exception)
    async def global_exception_handler(
        request,
        exc
    ):

        traceback.print_exc()


        return JSONResponse(

            status_code=500,

            content={

                "detail": str(exc)

            }

        )





    # =====================================================
    # API Routers
    # =====================================================

    prefix = settings.api_v1_prefix



    app.include_router(

        patient_routes.router,

        prefix=f"{prefix}/produce",

        tags=["Produce"]

    )


    app.include_router(

        market_routes.router,

        prefix=f"{prefix}/market",

        tags=["Market"]

    )


    app.include_router(

        twin_routes.router,

        prefix=f"{prefix}/twin",

        tags=["Digital Twin"]

    )


    app.include_router(

        prediction_routes.router,

        prefix=f"{prefix}/prediction",

        tags=["Prediction"]

    )


    app.include_router(

        simulation_routes.router,

        prefix=f"{prefix}/simulation",

        tags=["Simulation"]

    )


    app.include_router(

        dashboard_routes.router,

        prefix=f"{prefix}/dashboard",

        tags=["Dashboard"]

    )



    # websocket

    app.include_router(

        ws_manager.router,

        tags=["WebSocket"]

    )





    # =====================================================
    # Health
    # =====================================================


    @app.get(
        "/health",
        tags=["System"]
    )

    async def health_check():

        return {

            "status": "ok",

            "app": settings.app_name,

            "environment":
                settings.app_env,

        }





    @app.get(
        "/",
        tags=["System"]
    )

    async def root():

        return {

            "message":
                f"Welcome to {settings.app_name} API",

            "docs":
                "/docs"
                if not settings.is_production
                else "disabled in production"

        }



    return app






# =========================================================
# App Instance
# =========================================================

app = create_app()






# =========================================================
# Local Run
# =========================================================

if __name__ == "__main__":

    import uvicorn


    uvicorn.run(

        "app.main:app",

        host=settings.host,

        port=settings.port,

        reload=not settings.is_production,

    )