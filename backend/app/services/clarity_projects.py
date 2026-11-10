"""Clarity project registry: which Clarity project (API token) belongs to which GA4 property.

Token sources:
  db   - added from the UI, stored Fernet-encrypted with CLARITY_TOKEN_ENCRYPTION_KEY
  env  - CLARITY_TOKENS {"<property id>": "<token>"} or the legacy CLARITY_API_TOKEN (default property);
         the token stays in the environment and is never written to the database
  mock - MOCK_MODE projects; no token needed
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models import ClarityApiUsage, ClarityMetric, ClarityProject, ClarityRawSnapshot, ClaritySyncRun

log = logging.getLogger("app.clarity_projects")


# ---------------------------------------------------------------- encryption
def get_cipher(settings: Settings) -> Fernet | None:
    key = settings.clarity_token_encryption_key.strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as e:
        raise AppError(503, "encryption_key_invalid", "CLARITY_TOKEN_ENCRYPTION_KEY is not a valid Fernet key.",
                       hint='Generate one with: python -c "from cryptography.fernet import Fernet; '
                       'print(Fernet.generate_key().decode())"') from e


def require_cipher(settings: Settings) -> Fernet:
    cipher = get_cipher(settings)
    if cipher is None:
        raise AppError(503, "encryption_key_missing", "Set CLARITY_TOKEN_ENCRYPTION_KEY before saving Clarity tokens.",
                       hint='Generate a key with: python -c "from cryptography.fernet import Fernet; '
                       'print(Fernet.generate_key().decode())" — add it to .env and restart the backend. '
                       "Alternatively put tokens in CLARITY_TOKENS in .env.")
    return cipher


def encrypt_token(settings: Settings, token: str) -> str:
    return require_cipher(settings).encrypt(token.encode()).decode()


class TokenUnavailable(Exception):
    pass


def resolve_token(project: ClarityProject, settings: Settings) -> str:
    """The plaintext API token for a project. Raises TokenUnavailable with a readable reason."""
    if project.token_source == "mock":
        return "mock"
    if project.api_token_encrypted:
        cipher = get_cipher(settings)
        if cipher is None:
            raise TokenUnavailable("CLARITY_TOKEN_ENCRYPTION_KEY is not set, so the stored token can't be decrypted")
        try:
            return cipher.decrypt(project.api_token_encrypted.encode()).decode()
        except InvalidToken as e:
            raise TokenUnavailable("The stored token can't be decrypted — CLARITY_TOKEN_ENCRYPTION_KEY changed? "
                                   "Re-enter the token in Settings") from e
    if project.token_source == "env":
        token = settings.clarity_token_map().get(project.ga_property_id) or settings.clarity_api_token
        if token:
            return token
        raise TokenUnavailable(f"No token in CLARITY_TOKENS for property {project.ga_property_id} (or CLARITY_API_TOKEN)")
    raise TokenUnavailable("No API token saved for this project")


def has_token(project: ClarityProject, settings: Settings) -> bool:
    try:
        resolve_token(project, settings)
        return True
    except TokenUnavailable:
        return False


# ---------------------------------------------------------------- lookup
def all_projects(db: Session) -> list[ClarityProject]:
    return list(db.execute(select(ClarityProject).order_by(ClarityProject.ga_property_id)).scalars())


def project_for_property(db: Session, property_id: str) -> ClarityProject | None:
    return db.execute(select(ClarityProject).where(ClarityProject.ga_property_id == property_id)).scalar_one_or_none()


def linked_property_ids(db: Session, enabled_only: bool = True) -> set[str]:
    q = select(ClarityProject.ga_property_id)
    if enabled_only:
        q = q.where(ClarityProject.enabled.is_(True))
    return set(db.execute(q).scalars())


# ---------------------------------------------------------------- bootstrap
def seed_projects(db: Session, settings: Settings, default_property_id: str) -> list[str]:
    """Create project rows for env-configured tokens (and mock projects). Never overwrites a
    project managed from the UI. Returns the property IDs that were added."""
    wanted: dict[str, str] = {}  # property id -> token source
    if settings.mock_mode:
        from app.services.mock_data import MOCK_PROPERTIES

        wanted.update({pid: "mock" for _, _, pid, _, _, linked in MOCK_PROPERTIES if linked})
    for pid in settings.clarity_token_map():
        wanted[pid] = "env"
    if settings.clarity_api_token and default_property_id and default_property_id not in wanted:
        wanted[default_property_id] = "env"
    elif settings.clarity_api_token and not default_property_id:
        log.warning("CLARITY_API_TOKEN is set but the default GA4 property is unknown; set GA4_PROPERTY_ID "
                    "or use CLARITY_TOKENS to link it")

    added = []
    existing = {p.ga_property_id: p for p in all_projects(db)}
    for pid, source in wanted.items():
        if pid in existing:
            continue
        db.add(ClarityProject(ga_property_id=pid, label="", token_source=source, enabled=True))
        added.append(pid)
    if added:
        db.commit()
        log.info("Seeded Clarity projects for properties %s", ", ".join(added))
    return added


def adopt_unassigned_rows(db: Session, default_property_id: str) -> None:
    """Attach pre-multi-property data (property "" / project 0, left by the migration) to the default
    property and its Clarity project. Safe to call repeatedly; does nothing once everything is assigned."""
    if not default_property_id:
        return
    moved = db.execute(update(ClarityRawSnapshot).where(ClarityRawSnapshot.property_id == "")
                       .values(property_id=default_property_id)).rowcount
    db.execute(update(ClarityMetric).where(ClarityMetric.property_id == "").values(property_id=default_property_id))
    db.execute(update(ClaritySyncRun).where(ClaritySyncRun.property_id.is_(None)).values(property_id=default_property_id))

    project = project_for_property(db, default_property_id)
    if project is not None:
        db.execute(update(ClarityRawSnapshot).where(ClarityRawSnapshot.property_id == default_property_id,
                                                    ClarityRawSnapshot.clarity_project_id.is_(None))
                   .values(clarity_project_id=project.id))
        db.execute(update(ClarityMetric).where(ClarityMetric.property_id == default_property_id,
                                               ClarityMetric.clarity_project_id.is_(None))
                   .values(clarity_project_id=project.id))
        db.execute(update(ClaritySyncRun).where(ClaritySyncRun.property_id == default_property_id,
                                                ClaritySyncRun.clarity_project_id.is_(None))
                   .values(clarity_project_id=project.id))
        # Legacy quota counters (project 0) belong to the default project's token.
        for legacy in db.execute(select(ClarityApiUsage).where(ClarityApiUsage.clarity_project_id == 0)).scalars().all():
            current = db.get(ClarityApiUsage, (project.id, legacy.day))
            if current is None:
                db.add(ClarityApiUsage(clarity_project_id=project.id, day=legacy.day, calls=legacy.calls,
                                       exhausted=legacy.exhausted))
            else:
                current.calls = max(current.calls, legacy.calls)
                current.exhausted = current.exhausted or legacy.exhausted
            db.delete(legacy)
    db.commit()
    if moved:
        log.info("Assigned %d existing Clarity snapshot(s) to default property %s", moved, default_property_id)
