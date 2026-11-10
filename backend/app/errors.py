from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """An error rendered to the client as {"error": {"code", "message", "hint"}}."""

    def __init__(self, status_code: int, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.hint = hint


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "hint": exc.hint}},
    )
