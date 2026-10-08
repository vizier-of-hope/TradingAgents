"""python -m tradingagents.daily, with every collaborator faked."""

from datetime import date, datetime, timezone

import pytest

from tradingagents.daily.__main__ import Deps, main
from tradingagents.daily.recap import RecapDataError
from tradingagents.daily.schemas import DashboardEntry, DashboardReport, IndexQuote, MarketRecap
from tradingagents.daily.watchlist import WatchlistError

NOW = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)
ENV = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}

RECAP = MarketRecap(
    session_date=date(2026, 10, 5),
    indices=[IndexQuote(name="S&P 500", close=1.0, pct_change=0.1)],
    advancers=1, decliners=1, new_highs=0, new_lows=0, covered=2, total=2,
    leading=["Technology"], lagging=["Energy"],
)
REPORT = DashboardReport(
    session_date=date(2026, 10, 5), generated_at=NOW,
    entries=[DashboardEntry(ticker="NVDA", name="NVIDIA", rating="Hold", verdict="watch",
                            score=50, trend="bullish")],
)


class Fakes:
    def __init__(self, session=date(2026, 10, 5), recap=RECAP, watchlist=("NVDA",)):
        self.sent = []
        self.recap_dates = []
        self.clock_calls = 0
        self.dashboard_calls = 0
        self._session, self._recap, self._watchlist = session, recap, watchlist

    def deps(self):
        def send(texts, token, chat_id):
            self.sent.append(list(texts))

        def session_for(job, now_utc):
            self.clock_calls += 1
            return self._session

        def build_recap(session_date):
            self.recap_dates.append(session_date)
            if isinstance(self._recap, BaseException):
                raise self._recap
            return self._recap

        def run_dashboard(tickers, session_date, now_utc):
            self.dashboard_calls += 1
            return REPORT, 37

        def load_watchlist(path):
            if isinstance(self._watchlist, BaseException):
                raise self._watchlist
            return list(self._watchlist)

        return Deps(send=send, run_dashboard=run_dashboard, build_recap=build_recap,
                    session_for=session_for, load_watchlist=load_watchlist)


def test_no_session_sends_nothing(capsys):
    fakes = Fakes(session=None)
    assert main(["recap"], now_utc=NOW, env=ENV, deps=fakes.deps()) == 0
    assert fakes.sent == []
    assert "nothing sent" in capsys.readouterr().out


def test_recap_sends_rendered_message():
    fakes = Fakes()
    assert main(["recap"], now_utc=NOW, env=ENV, deps=fakes.deps()) == 0
    assert fakes.sent[0][0].startswith("🎯 2026-10-05 Market Recap")


def test_dry_run_prints_and_does_not_send(capsys):
    fakes = Fakes()
    assert main(["recap", "--dry-run"], now_utc=NOW, env={}, deps=fakes.deps()) == 0
    assert fakes.sent == []
    assert "Market Recap" in capsys.readouterr().out


def test_date_override_skips_clock():
    fakes = Fakes()
    main(["recap", "--date", "2026-10-02"], now_utc=NOW, env=ENV, deps=fakes.deps())
    assert fakes.clock_calls == 0
    assert fakes.recap_dates == [date(2026, 10, 2)]


def test_missing_telegram_env_returns_2(capsys):
    fakes = Fakes()
    assert main(["recap"], now_utc=NOW, env={}, deps=fakes.deps()) == 2
    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().err
    assert fakes.recap_dates == []


def test_dashboard_prints_call_count(capsys):
    fakes = Fakes()
    assert main(["dashboard"], now_utc=NOW, env=ENV, deps=fakes.deps()) == 0
    assert "LLM calls: 37" in capsys.readouterr().out
    assert fakes.sent[0][0].startswith("🎯 2026-10-05 Decision Dashboard")


def test_crash_sends_failure_then_raises():
    fakes = Fakes(recap=RecapDataError("no ^DJI"))
    with pytest.raises(RecapDataError):
        main(["recap"], now_utc=NOW, env=ENV, deps=fakes.deps())
    assert fakes.sent == [["❌ Recap run failed: RecapDataError: no ^DJI"]]


def test_failure_notice_send_error_does_not_mask_original():
    fakes = Fakes(recap=RecapDataError("no ^DJI"))
    deps = fakes.deps()

    def broken_send(texts, token, chat_id):
        raise ConnectionError("telegram down")

    deps.send = broken_send
    with pytest.raises(RecapDataError):
        main(["recap"], now_utc=NOW, env=ENV, deps=deps)


def test_bad_watchlist_fails_before_llm():
    fakes = Fakes(watchlist=WatchlistError("line 2: not a ticker"))
    with pytest.raises(WatchlistError):
        main(["dashboard"], now_utc=NOW, env=ENV, deps=fakes.deps())
    assert fakes.dashboard_calls == 0
    assert fakes.sent == [["❌ Dashboard run failed: WatchlistError: line 2: not a ticker"]]
