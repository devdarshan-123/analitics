from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """All configuration comes from environment variables / .env (repo root or backend/)."""

    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        extra="ignore",
    )

    mock_mode: bool = False

    # Optional default property. If unset (or not accessible), the first discovered property is used.
    ga4_property_id: str = ""
    google_application_credentials: str = ""
    # Optional comma-separated property IDs; when set, only these properties are listed/queryable.
    ga_property_allowlist: str = ""
    properties_cache_ttl_seconds: int = 3600

    # Legacy single token: used for the default property's Clarity project.
    clarity_api_token: str = ""
    # JSON object mapping GA4 property ID -> Clarity API token, e.g. {"560115218": "token-a"}
    clarity_tokens: str = ""
    # Fernet key for tokens added from the UI (generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    clarity_token_encryption_key: str = ""
    clarity_base_url: str = "https://www.clarity.ms/export-data/api/v1/project-live-insights"
    clarity_daily_limit: int = 10
    # Refuse to call Clarity once this many calls have been used in the current UTC day.
    clarity_safety_limit: int = 9
    clarity_max_calls_per_run: int = 6

    database_url: str = "sqlite:///./analytics.db"

    dashboard_password: str = ""
    session_secret: str = ""
    session_max_age_hours: int = 72
    cookie_secure: bool = False

    tz: str = "Asia/Kolkata"
    cors_origins: str = "http://localhost:5173"

    enable_scheduler: bool = True
    clarity_sync_hour: int = 2
    clarity_sync_minute: int = 0

    ga_cache_ttl_seconds: int = 600

    # Report: hostnames/sources containing any of these (comma-separated) count as internal traffic.
    report_internal_hosts: str = "localhost,127.0.0.1,staging."
    # JSON {GA property ID: Clarity project ID} so report links open the right Clarity project,
    # e.g. {"560115218": "z1tvrpoq6h"} (the ID in clarity.microsoft.com/projects/view/<id>/...).
    clarity_project_links: str = ""
    ga_realtime_cache_ttl_seconds: int = 60

    log_level: str = "INFO"

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def internal_host_patterns(self) -> list[str]:
        return [p.strip().lower() for p in self.report_internal_hosts.split(",") if p.strip()]

    def clarity_link_map(self) -> dict[str, str]:
        import json

        try:
            data = json.loads(self.clarity_project_links) if self.clarity_project_links.strip() else {}
        except ValueError:
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    @property
    def property_allowlist(self) -> set[str]:
        return {p.strip() for p in self.ga_property_allowlist.split(",") if p.strip()}

    def clarity_token_map(self) -> dict[str, str]:
        """CLARITY_TOKENS parsed into {property_id: token}. Malformed JSON is logged and ignored."""
        import json
        import logging

        if not self.clarity_tokens.strip():
            return {}
        try:
            data = json.loads(self.clarity_tokens)
        except ValueError:
            logging.getLogger("app.config").error("CLARITY_TOKENS is not valid JSON; ignoring it")
            return {}
        if not isinstance(data, dict):
            logging.getLogger("app.config").error("CLARITY_TOKENS must be a JSON object of property ID -> token; ignoring it")
            return {}
        return {str(k).strip(): str(v).strip() for k, v in data.items() if str(k).strip() and v}

    @property
    def sqlalchemy_url(self) -> str:
        """Normalise Postgres URLs (Render/Supabase give postgres://) to the psycopg3 driver."""
        url = self.database_url
        if self.mock_mode and url == "sqlite:///./analytics.db":
            # Keep seeded fake data out of the real database.
            return "sqlite:///./analytics_mock.db"
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    def credentials_path(self) -> Path | None:
        if not self.google_application_credentials:
            return None
        p = Path(self.google_application_credentials)
        if p.is_absolute() or p.exists():
            return p
        candidate = REPO_ROOT / p
        return candidate if candidate.exists() else p


@lru_cache
def get_settings() -> Settings:
    return Settings()
