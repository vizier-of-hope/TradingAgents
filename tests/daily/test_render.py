"""Telegram text for the dashboard and the recap."""

from datetime import date, datetime, timezone

from tradingagents.daily.render import render_dashboard, render_failure, render_recap
from tradingagents.daily.schemas import (
    DashboardEntry,
    DashboardReport,
    IndexQuote,
    MarketRecap,
)

GENERATED = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)  # 19:00 SGT

NVDA = DashboardEntry(
    ticker="NVDA", name="NVIDIA Corporation", rating="Hold", verdict="watch",
    score=62, trend="bullish",
    sentiment="Upbeat on AI demand.", earnings_outlook="Revenue grew 56% last quarter.",
    risks=["Export limits to China."], catalysts=["New GPU launch in Q4."],
    latest="Announced a $5B buyback.",
)
AAPL = DashboardEntry(
    ticker="AAPL", name="Apple Inc.", rating="Underweight", verdict="sell",
    score=35, trend="bearish", sentiment="Cautious.", earnings_outlook="Flat.",
    latest="Quiet week.",
)
XYZ = DashboardEntry(
    ticker="XYZ", name="XYZ Inc", rating="REVIEW", verdict="review",
    note="Analysis failed: ValueError",
)
MSFT = DashboardEntry(
    ticker="MSFT", name="Microsoft Corporation", rating="", verdict="skipped",
    note="daily model quota reached",
)


def _report(*entries):
    return DashboardReport(session_date=date(2026, 10, 5), generated_at=GENERATED,
                           entries=list(entries))


def test_dashboard_summary_counts_and_lines():
    msgs = render_dashboard(_report(NVDA, AAPL, XYZ))
    assert msgs[0].splitlines()[:2] == [
        "🎯 2026-10-05 Decision Dashboard",
        "2 stocks analyzed | 🟢 Buy: 0  🟡 Watch: 1  🔴 Sell: 1",
    ]
    assert "🟡 NVIDIA Corporation (NVDA): Watch (Hold) | Score 62 | Bullish" in msgs[0]
    assert "🔴 Apple Inc. (AAPL): Sell (Underweight) | Score 35 | Bearish" in msgs[0]
    assert "⚠️ XYZ Inc (XYZ): Analysis failed: ValueError" in msgs[0]
    assert len(msgs) == 3


def test_dashboard_stock_message_exact():
    msgs = render_dashboard(_report(NVDA))
    assert msgs[1] == (
        "🟡 NVIDIA Corporation (NVDA)\n"
        "📰 Key Info\n"
        "💭 Sentiment: Upbeat on AI demand.\n"
        "📊 Earnings outlook: Revenue grew 56% last quarter.\n"
        "\n"
        "🚨 Risks:\n"
        "• Export limits to China.\n"
        "✨ Catalysts:\n"
        "• New GPU launch in Q4.\n"
        "📢 Latest: Announced a $5B buyback.\n"
        "\n"
        "---\n"
        "Generated: 19:00 SGT"
    )


def test_footer_only_on_last_message():
    msgs = render_dashboard(_report(NVDA, AAPL))
    assert "Generated:" not in msgs[0] and "Generated:" not in msgs[1]
    assert msgs[2].endswith("---\nGenerated: 19:00 SGT")


def test_footer_on_summary_when_no_stock_messages():
    msgs = render_dashboard(_report(XYZ, MSFT))
    assert len(msgs) == 1
    assert msgs[0].startswith("🎯 2026-10-05 Decision Dashboard\n0 stocks analyzed")
    assert msgs[0].endswith("---\nGenerated: 19:00 SGT")


def test_empty_lists_render_none_identified():
    msgs = render_dashboard(_report(AAPL))
    assert "🚨 Risks:\n• None identified\n✨ Catalysts:\n• None identified" in msgs[1]


def test_skipped_line():
    msgs = render_dashboard(_report(NVDA, MSFT))
    assert "⏭ Microsoft Corporation (MSFT): daily model quota reached" in msgs[0]


def test_fallback_entry_without_score():
    fallback = DashboardEntry(ticker="AMD", name="AMD", rating="Buy", verdict="buy",
                              note="Strong data-center demand. Margins expanding.")
    msgs = render_dashboard(_report(fallback))
    assert "🟢 AMD (AMD): Buy (Buy)\n" in msgs[0] + "\n"
    assert msgs[1].startswith("🟢 AMD (AMD)\n📝 Strong data-center demand. Margins expanding.\n")


def test_trend_labels():
    rng = NVDA.model_copy(update={"trend": "range_bound"})
    assert "| Range-bound" in render_dashboard(_report(rng))[0]


RECAP = MarketRecap(
    session_date=date(2026, 10, 5),
    indices=[IndexQuote(name="S&P 500", close=6712.4, pct_change=0.85),
             IndexQuote(name="Nasdaq", close=22841.1, pct_change=0.0),
             IndexQuote(name="Dow", close=46120.55, pct_change=-0.12)],
    advancers=352, decliners=148, new_highs=41, new_lows=6, covered=500, total=503,
    leading=["Technology", "Communication Services", "Materials"],
    lagging=["Utilities", "Real Estate", "Energy"],
)


def test_recap_exact():
    assert render_recap(RECAP) == (
        "🎯 2026-10-05 Market Recap\n"
        "\n"
        "📊 Major Indices\n"
        "- S&P 500: 6712.40 (🟢+0.85%)\n"
        "- Nasdaq: 22841.10 (🟢+0.00%)\n"
        "- Dow: 46120.55 (🔴-0.12%)\n"
        "\n"
        "📈 Market Breadth (S&P 500)\n"
        "Up: 352 | Down: 148 | 52w Highs: 41 | 52w Lows: 6\n"
        "\n"
        "🔥 Sectors\n"
        "Leading: Technology, Communication Services, Materials\n"
        "Lagging: Utilities, Real Estate, Energy"
    )


def test_recap_partial_coverage_heading():
    recap = RECAP.model_copy(update={"covered": 471})
    assert "📈 Market Breadth (S&P 500) (471/503)" in render_recap(recap)


def test_recap_95_percent_coverage_no_count():
    recap = RECAP.model_copy(update={"covered": 480})  # 95.4%
    assert "📈 Market Breadth (S&P 500)\n" in render_recap(recap)


def test_failure_message():
    assert render_failure("dashboard", ValueError("boom")) == "❌ Dashboard run failed: ValueError: boom"
