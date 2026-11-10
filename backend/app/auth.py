"""Single-password auth with an HMAC-signed, HTTP-only session cookie."""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Request, Response

from app.config import Settings, get_settings
from app.errors import AppError

COOKIE_NAME = "dash_session"


def _secret(settings: Settings) -> bytes:
    if settings.session_secret:
        return settings.session_secret.encode()
    # Derived from the password, so changing the password invalidates every session.
    return hashlib.sha256(f"analytics-dashboard:{settings.dashboard_password}".encode()).digest()


def make_token(settings: Settings, now: float | None = None) -> str:
    expires = int((now or time.time()) + settings.session_max_age_hours * 3600)
    sig = hmac.new(_secret(settings), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def verify_token(settings: Settings, token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token or not settings.dashboard_password:
        return False
    expires_s, sig = token.split(".", 1)
    if not expires_s.isdigit():
        return False
    expected = hmac.new(_secret(settings), expires_s.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected) and int(expires_s) > (now or time.time())


def check_password(settings: Settings, password: str) -> bool:
    if not settings.dashboard_password:
        raise AppError(503, "auth_not_configured", "DASHBOARD_PASSWORD is not set on the server.")
    return hmac.compare_digest(password.encode(), settings.dashboard_password.encode())


def set_session_cookie(response: Response, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        make_token(settings),
        max_age=settings.session_max_age_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def require_auth(request: Request) -> None:
    """FastAPI dependency guarding every /api route except health and login."""
    if not verify_token(get_settings(), request.cookies.get(COOKIE_NAME)):
        raise AppError(401, "unauthenticated", "Please sign in.")
