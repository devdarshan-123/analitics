from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, Response

from app.auth import COOKIE_NAME, check_password, clear_session_cookie, set_session_cookie, verify_token
from app.config import get_settings
from app.errors import AppError
from app.schemas import AuthStatus, LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=AuthStatus)
async def login(body: LoginRequest, response: Response) -> AuthStatus:
    settings = get_settings()
    if not check_password(settings, body.password):
        await asyncio.sleep(0.75)  # slow down guessing
        raise AppError(401, "invalid_password", "Incorrect password.")
    set_session_cookie(response, settings)
    return AuthStatus(authenticated=True, mock_mode=settings.mock_mode)


@router.post("/logout", response_model=AuthStatus)
def logout(response: Response) -> AuthStatus:
    clear_session_cookie(response)
    return AuthStatus(authenticated=False, mock_mode=get_settings().mock_mode)


@router.get("/me", response_model=AuthStatus)
def me(request: Request) -> AuthStatus:
    settings = get_settings()
    return AuthStatus(authenticated=verify_token(settings, request.cookies.get(COOKIE_NAME)), mock_mode=settings.mock_mode)
