from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import Query

from app.config import get_settings
from app.errors import AppError


def local_today() -> date:
    return datetime.now(get_settings().zone).date()


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date
    compare: bool = False

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def previous(self) -> "DateRange":
        prev_end = self.start - timedelta(days=1)
        return DateRange(prev_end - timedelta(days=self.days - 1), prev_end)

    def iter_days(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.days)]


def date_range_params(
    start: date | None = Query(None, description="YYYY-MM-DD, default 30 days ago"),
    end: date | None = Query(None, description="YYYY-MM-DD, default today"),
    compare: bool = Query(False, description="Also return the previous period of equal length"),
) -> DateRange:
    end = end or local_today()
    start = start or end - timedelta(days=29)
    if start > end:
        raise AppError(400, "invalid_range", "start must be on or before end")
    if (end - start).days > 730:
        raise AppError(400, "invalid_range", "Date range cannot exceed two years")
    return DateRange(start, end, compare)
