from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClarityProject(Base):
    """One Microsoft Clarity project, linked to exactly one GA4 property.

    Tokens added from the UI are stored Fernet-encrypted in `api_token_encrypted`. Projects seeded
    from CLARITY_TOKENS / CLARITY_API_TOKEN leave it empty and read the token from the environment,
    so env secrets are never copied into the database.
    """

    __tablename__ = "clarity_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ga_property_id: Mapped[str] = mapped_column(String(32), unique=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    api_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # db (encrypted token above) | env (CLARITY_TOKENS / CLARITY_API_TOKEN) | mock
    token_source: Mapped[str] = mapped_column(String(10), default="db")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClarityRawSnapshot(Base):
    """Raw Clarity API response, one row per (property, snapshot_date, dimension set, numOfDays)."""

    __tablename__ = "clarity_raw_snapshots"
    __table_args__ = (
        UniqueConstraint("property_id", "snapshot_date", "dimensions", "num_of_days", name="uq_snapshot_property"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    # Which Clarity project produced it (kept even if the project row is later removed).
    clarity_project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    # Pipe-joined dimension names, "" for overall totals, e.g. "URL" or "Device|OS"
    dimensions: Mapped[str] = mapped_column(String(200), default="")
    num_of_days: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[Any] = mapped_column(JSON)


class ClarityMetric(Base):
    """Normalised Clarity values: one numeric field of one metric for one dimension value."""

    __tablename__ = "clarity_metrics"
    __table_args__ = (
        Index("ix_metrics_property_lookup", "property_id", "dimensions", "num_of_days", "snapshot_date"),
        Index("ix_metrics_name", "metric_name", "field_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("clarity_raw_snapshots.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[str] = mapped_column(String(32), default="")
    clarity_project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_date: Mapped[date] = mapped_column(Date)
    num_of_days: Mapped[int] = mapped_column(Integer, default=1)
    dimensions: Mapped[str] = mapped_column(String(200), default="")
    metric_name: Mapped[str] = mapped_column(String(100))
    dimension_key: Mapped[str] = mapped_column(String(200), default="")
    dimension_value: Mapped[str] = mapped_column(Text, default="")
    field_name: Mapped[str] = mapped_column(String(100))
    value: Mapped[float] = mapped_column(Float)


class ClarityApiUsage(Base):
    """Clarity API calls made per project per UTC day (the API allows 10 per project per day)."""

    __tablename__ = "clarity_api_usage"

    clarity_project_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    exhausted: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ClaritySyncRun(Base):
    """One sync attempt for one Clarity project."""

    __tablename__ = "clarity_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    clarity_project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # scheduled | manual | cli
    status: Mapped[str] = mapped_column(String(20), default="running")  # success | partial | skipped | failed
    calls_made: Mapped[int] = mapped_column(Integer, default=0)
    snapshots_stored: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
