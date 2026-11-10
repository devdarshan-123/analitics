from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.db import engine

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health() -> dict[str, str | bool]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db = "ok"
    except Exception:
        db = "error"
    return {"status": "ok" if db == "ok" else "degraded", "db": db, "mock_mode": get_settings().mock_mode}
