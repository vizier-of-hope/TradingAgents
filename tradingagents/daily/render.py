"""Plain-text Telegram messages for the dashboard and the recap.

Plain text (no parse mode) so nothing a model writes can break the formatting.
"""

from __future__ import annotations

from .market_clock import SGT
from .schemas import DashboardEntry, DashboardReport, MarketRecap

EMOJI = {"buy": "🟢", "watch": "🟡", "sell": "🔴", "review": "⚠️", "skipped": "⏭"}
VERDICT_LABEL = {"buy": "Buy", "watch": "Watch", "sell": "Sell"}
TREND_LABEL = {"bullish": "Bullish", "range_bound": "Range-bound", "bearish": "Bearish"}
ANALYZED = ("buy", "watch", "sell")
FULL_COVERAGE = 0.95


def _footer(report: DashboardReport) -> str:
    return f"\n\n---\nGenerated: {report.generated_at.astimezone(SGT):%H:%M} SGT"


def _summary_line(entry: DashboardEntry) -> str:
    head = f"{EMOJI[entry.verdict]} {entry.name} ({entry.ticker})"
    if entry.verdict not in ANALYZED:
        return f"{head}: {entry.note}"
    line = f"{head}: {VERDICT_LABEL[entry.verdict]} ({entry.rating})"
    if entry.score is not None:
        line += f" | Score {entry.score}"
    if entry.trend is not None:
        line += f" | {TREND_LABEL[entry.trend]}"
    return line


def _bullets(items: list[str]) -> str:
    return "\n".join(f"• {item}" for item in items) if items else "• None identified"


def _stock_message(entry: DashboardEntry) -> str:
    head = f"{EMOJI[entry.verdict]} {entry.name} ({entry.ticker})"
    if entry.score is None:
        # Fallback entry: the extractor failed, so only the decision's summary is known.
        return f"{head}\n📝 {entry.note}"
    return (
        f"{head}\n"
        f"📰 Key Info\n"
        f"💭 Sentiment: {entry.sentiment}\n"
        f"📊 Earnings outlook: {entry.earnings_outlook}\n"
        f"\n"
        f"🚨 Risks:\n{_bullets(entry.risks)}\n"
        f"✨ Catalysts:\n{_bullets(entry.catalysts)}\n"
        f"📢 Latest: {entry.latest}"
    )


def render_dashboard(report: DashboardReport) -> list[str]:
    """The summary message, then one message per analysed stock.

    The "Generated" footer goes on the last message only.
    """
    counts = {v: sum(e.verdict == v for e in report.entries) for v in ANALYZED}
    summary = (
        f"🎯 {report.session_date.isoformat()} Decision Dashboard\n"
        f"{sum(counts.values())} stocks analyzed | "
        f"🟢 Buy: {counts['buy']}  🟡 Watch: {counts['watch']}  🔴 Sell: {counts['sell']}\n"
        f"\n"
        f"📊 Summary\n"
        + "\n".join(_summary_line(e) for e in report.entries)
    )
    messages = [summary] + [_stock_message(e) for e in report.entries if e.verdict in ANALYZED]
    messages[-1] += _footer(report)
    return messages


def _change(pct: float) -> str:
    return f"{'🟢' if pct >= 0 else '🔴'}{pct:+.2f}%"


def render_recap(recap: MarketRecap) -> str:
    breadth_heading = "📈 Market Breadth (S&P 500)"
    if recap.total and recap.covered / recap.total < FULL_COVERAGE:
        breadth_heading += f" ({recap.covered}/{recap.total})"
    indices = "\n".join(f"- {q.name}: {q.close:.2f} ({_change(q.pct_change)})" for q in recap.indices)
    return (
        f"🎯 {recap.session_date.isoformat()} Market Recap\n"
        f"\n"
        f"📊 Major Indices\n{indices}\n"
        f"\n"
        f"{breadth_heading}\n"
        f"Up: {recap.advancers} | Down: {recap.decliners} | "
        f"52w Highs: {recap.new_highs} | 52w Lows: {recap.new_lows}\n"
        f"\n"
        f"🔥 Sectors\n"
        f"Leading: {', '.join(recap.leading)}\n"
        f"Lagging: {', '.join(recap.lagging)}"
    )


def render_failure(job: str, exc: BaseException) -> str:
    return f"❌ {job.title()} run failed: {type(exc).__name__}: {exc}"
