"""Which US session each daily job reports on, from a fixed SGT schedule."""

from datetime import UTC, date, datetime

import pytest

from tradingagents.daily.market_clock import session_for

U = UTC


def test_dashboard_normal_tuesday():
    # 2026-10-06 11:00Z = Tue 19:00 SGT = 07:00 ET
    assert session_for("dashboard", datetime(2026, 10, 6, 11, 0, tzinfo=U)) == date(2026, 10, 5)


def test_dashboard_monday_reports_friday():
    assert session_for("dashboard", datetime(2026, 10, 5, 11, 0, tzinfo=U)) == date(2026, 10, 2)


def test_dashboard_skips_us_holiday():
    # Thanksgiving 2026-11-26
    assert session_for("dashboard", datetime(2026, 11, 26, 11, 0, tzinfo=U)) is None


def test_dashboard_day_after_holiday_reports_day_before_holiday():
    assert session_for("dashboard", datetime(2026, 11, 27, 11, 0, tzinfo=U)) == date(2026, 11, 25)


def test_recap_normal():
    # 2026-10-06 22:00Z = Wed 06:00 SGT = Tue 18:00 ET
    assert session_for("recap", datetime(2026, 10, 6, 22, 0, tzinfo=U)) == date(2026, 10, 6)


def test_recap_holiday_none():
    assert session_for("recap", datetime(2026, 11, 26, 22, 0, tzinfo=U)) is None


def test_recap_early_close_runs():
    # 2026-11-27 closes at 13:00 ET
    assert session_for("recap", datetime(2026, 11, 27, 22, 0, tzinfo=U)) == date(2026, 11, 27)


def test_recap_winter_time():
    # EST: 2026-12-15 22:00Z = 17:00 ET
    assert session_for("recap", datetime(2026, 12, 15, 22, 0, tzinfo=U)) == date(2026, 12, 15)


def test_naive_now_rejected():
    with pytest.raises(ValueError):
        session_for("recap", datetime(2026, 10, 6, 22, 0))
