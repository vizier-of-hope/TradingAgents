"""Which NYSE session a daily job reports on.

Both jobs run at fixed SGT times (UTC+8, no daylight saving), which land at
different New York hours in summer and winter but on the same New York date:

- dashboard, 19:00 SGT = 06:00-07:00 ET, before that day's open;
- recap, 06:00 SGT = 17:00-18:00 ET, after that day's close.
"""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

import exchange_calendars

SGT = ZoneInfo("Asia/Singapore")
NY = ZoneInfo("America/New_York")


@lru_cache(maxsize=1)
def _nyse():
    return exchange_calendars.get_calendar("XNYS")


def session_for(job: Literal["dashboard", "recap"], now_utc: datetime) -> date | None:
    """The US session date ``job`` reports on, or ``None`` when it should not send.

    dashboard: nothing when New York's today is not a trading day (the market
    will not open); otherwise the last completed session before today.
    recap: New York's today when it was a trading day, else nothing.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    ny_today = now_utc.astimezone(NY).date()
    calendar = _nyse()
    if not calendar.is_session(ny_today):
        return None
    if job == "recap":
        return ny_today
    if job == "dashboard":
        return calendar.previous_session(ny_today).date()
    raise ValueError(f"unknown job: {job!r}")
