from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors import AppError, app_error_handler


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    # httpx logs full URLs at INFO; our own client logs a sanitised line instead.
    logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    from app.db import SessionLocal, init_db
    from app.jobs.scheduler import start_scheduler, stop_scheduler

    from app.jobs.clarity_sync import bootstrap, seed_mock_history

    settings = get_settings()
    init_db()
    with SessionLocal() as db:
        try:
            bootstrap(db, settings)  # seed env/mock Clarity projects, attach legacy data to the default property
        except Exception:
            logging.getLogger("app").exception("Clarity project bootstrap failed; will retry on the next sync")
        if settings.mock_mode:
            seed_mock_history(db, settings)
    if settings.mock_mode:
        logging.getLogger("app").warning("MOCK_MODE is on — serving fake GA4 and Clarity data")
    if settings.enable_scheduler:
        start_scheduler()
    yield
    stop_scheduler()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Analytics Dashboard API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []))
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request",
                                                                 "message": f"{where}: {first.get('msg', 'invalid')}", "hint": None}})

    from app.routers import admin, auth, clarity, combined, ga, health, properties

    for r in (health.router, auth.router, properties.router, ga.router, clarity.router, combined.router, admin.router):
        app.include_router(r)
    return app


app = create_app()
