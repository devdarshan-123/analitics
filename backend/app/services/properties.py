"""Discover the GA4 properties the service account can read (Analytics Admin API).

The list is cached for an hour (PROPERTIES_CACHE_TTL_SECONDS), filtered by GA_PROPERTY_ALLOWLIST,
and doubles as the authorisation list: GA/Clarity endpoints refuse property IDs that are not in it.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from google.api_core import exceptions as gexc

from app.config import get_settings
from app.errors import AppError

log = logging.getLogger("app.properties")

ACCESS_HINT = (
    'Enable "Google Analytics Admin API" in Google Cloud Console (APIs & Services → Library) for the '
    "service account's project, then in Google Analytics add the service-account email{email} as Viewer at "
    "the ACCOUNT level (Admin → Account access management) so it sees every property in that account — "
    "or add it per property (Admin → Property access management)."
)


@dataclass(frozen=True)
class GAProperty:
    account_id: str
    account_name: str
    property_id: str
    property_name: str


def sort_properties(props: list[GAProperty]) -> list[GAProperty]:
    return sorted(props, key=lambda p: (p.account_name.casefold(), p.account_id, p.property_name.casefold(), p.property_id))


def service_account_email(credentials_path: Path | None) -> str | None:
    if not credentials_path:
        return None
    try:
        return json.loads(credentials_path.read_text(encoding="utf-8")).get("client_email")
    except (OSError, ValueError, AttributeError):
        return None


def access_error(code: str, message: str, detail: str | None = None) -> AppError:
    email = service_account_email(get_settings().credentials_path())
    hint = ACCESS_HINT.format(email=f" ({email})" if email else "")
    return AppError(503, code, message, hint=f"{hint} ({detail})" if detail else hint)


# ---------------------------------------------------------------- sources
def fetch_from_admin_api(credentials_path: Path | None) -> list[GAProperty]:
    """Every account → property visible to the credentials, via list_account_summaries (auto-paginated)."""
    from google.analytics.admin_v1beta import AnalyticsAdminServiceClient
    from google.analytics.admin_v1beta.types import ListAccountSummariesRequest
    from google.auth.exceptions import DefaultCredentialsError

    try:
        if credentials_path:
            if not credentials_path.exists():
                raise AppError(503, "ga_credentials_missing", f"Service-account key file not found: {credentials_path}",
                               hint="Check GOOGLE_APPLICATION_CREDENTIALS in .env.")
            client = AnalyticsAdminServiceClient.from_service_account_file(str(credentials_path))
        else:
            client = AnalyticsAdminServiceClient()
    except DefaultCredentialsError as e:
        raise AppError(503, "ga_credentials_missing", "No Google credentials found.",
                       hint="Set GOOGLE_APPLICATION_CREDENTIALS to your service-account JSON key.") from e
    except ValueError as e:
        raise AppError(503, "ga_credentials_invalid", "Service-account key file is invalid.", hint=str(e)) from e

    started = time.perf_counter()
    out: list[GAProperty] = []
    try:
        for account in client.list_account_summaries(request=ListAccountSummariesRequest(page_size=200)):
            account_id = account.account.split("/")[-1]
            for p in account.property_summaries:
                out.append(GAProperty(account_id=account_id, account_name=account.display_name or account_id,
                                      property_id=p.property.split("/")[-1], property_name=p.display_name or p.property))
    except gexc.PermissionDenied as e:
        raise access_error("ga_admin_api_unavailable", "Couldn't list your GA4 properties: the Google Analytics Admin "
                           "API is disabled or the service account has no access.", getattr(e, "message", str(e))) from e
    except gexc.GoogleAPICallError as e:
        raise AppError(502, "ga_admin_api_error", "Google Analytics Admin API error while listing properties.",
                       hint=getattr(e, "message", None) or str(e)) from e
    finally:
        log.info("GA listAccountSummaries properties=%d duration=%.0fms", len(out), (time.perf_counter() - started) * 1000)
    return out


def mock_properties() -> list[GAProperty]:
    from app.services.mock_data import MOCK_PROPERTIES

    return [GAProperty(*p[:4]) for p in MOCK_PROPERTIES]


# ---------------------------------------------------------------- directory
class PropertyDirectory:
    """Cached, allowlist-filtered, sorted property list. Failures are cached briefly so a broken
    Admin API doesn't get hammered by every dashboard request."""

    def __init__(self, fetch: Callable[[], list[GAProperty]], ttl: float = 3600, error_ttl: float = 60,
                 allowlist: set[str] | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._fetch = fetch
        self.ttl = ttl
        self.error_ttl = error_ttl
        self.allowlist = allowlist or set()
        self._clock = clock
        self._lock = threading.Lock()
        self._value: list[GAProperty] | None = None
        self._error: AppError | None = None
        self._expires = 0.0
        self.fetched_at: float | None = None  # wall-clock seconds of the last successful fetch

    def list(self, refresh: bool = False) -> list[GAProperty]:
        with self._lock:
            if not refresh and self._clock() < self._expires:
                if self._error:
                    raise self._error
                return list(self._value or [])
            try:
                props = self._load()
            except AppError as e:
                self._value, self._error, self._expires = None, e, self._clock() + self.error_ttl
                raise
            self._value, self._error, self._expires = props, None, self._clock() + self.ttl
            self.fetched_at = time.time()
            return list(props)

    def _load(self) -> list[GAProperty]:
        raw = self._fetch()
        props = [p for p in raw if not self.allowlist or p.property_id in self.allowlist]
        # De-duplicate (a property can only appear once, but be defensive about pagination overlaps).
        props = sort_properties(list({p.property_id: p for p in props}.values()))
        if not props:
            if raw and self.allowlist:
                raise AppError(503, "ga_no_properties", "No GA4 properties match GA_PROPERTY_ALLOWLIST.",
                               hint=f"The service account can see {len(raw)} propert{'y' if len(raw) == 1 else 'ies'}, "
                               "but none of their IDs are in GA_PROPERTY_ALLOWLIST. Check the IDs (numeric, not G-XXXX).")
            raise access_error("ga_no_properties", "The service account can't see any GA4 properties.")
        return props

    def ids(self) -> set[str]:
        return {p.property_id for p in self.list()}

    def default_id(self, configured: str = "") -> str:
        props = self.list()
        if configured and any(p.property_id == configured for p in props):
            return configured
        if configured:
            log.warning("GA4_PROPERTY_ID=%s is not among the accessible properties; defaulting to %s",
                        configured, props[0].property_id)
        return props[0].property_id

    def clear(self) -> None:
        with self._lock:
            self._value, self._error, self._expires = None, None, 0.0


@lru_cache
def get_directory() -> PropertyDirectory:
    s = get_settings()
    fetch = mock_properties if s.mock_mode else (lambda: fetch_from_admin_api(s.credentials_path()))
    return PropertyDirectory(fetch, ttl=s.properties_cache_ttl_seconds, allowlist=s.property_allowlist)


def default_property_id() -> str:
    """The default property, or "" if it can't be determined (e.g. Admin API unavailable and no GA4_PROPERTY_ID)."""
    s = get_settings()
    try:
        return get_directory().default_id(s.ga4_property_id)
    except AppError as e:
        if s.ga4_property_id and (not s.property_allowlist or s.ga4_property_id in s.property_allowlist):
            return s.ga4_property_id
        log.warning("No default GA4 property: %s", e.message)
        return ""


def resolve_property_id(requested: str | None) -> str:
    """Validate a ?propertyId= against the discovered list (403 if not in it); default when missing.

    If discovery itself fails, the configured GA4_PROPERTY_ID keeps working so a broken Admin API
    setup doesn't take down a dashboard that worked before multi-property support.
    """
    s = get_settings()
    directory = get_directory()
    try:
        ids = directory.ids()
    except AppError:
        fallback = s.ga4_property_id
        if fallback and requested in (None, fallback) and (not s.property_allowlist or fallback in s.property_allowlist):
            return fallback
        raise
    if requested is None:
        return directory.default_id(s.ga4_property_id)
    if requested not in ids:
        raise AppError(403, "property_not_allowed", f"GA4 property {requested} is not available to this dashboard.",
                       hint="Pick a property from the list. If it should be there, refresh the property list, check "
                       "GA_PROPERTY_ALLOWLIST, and make sure the service account has Viewer access to it.")
    return requested
