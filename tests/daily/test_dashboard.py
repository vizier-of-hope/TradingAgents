"""Dashboard orchestration with a fake graph and a fake extractor: no LLM, no network."""

from datetime import date, datetime, timezone

import pytest

from tradingagents.daily.dashboard import (
    extract_prompt,
    is_quota_error,
    lean_config,
    run_dashboard,
    selected_analysts,
)
from tradingagents.daily.schemas import ExtractedFields

SESSION = date(2026, 10, 5)
NOW = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)


class RateLimitError(Exception):
    """Same class name as openai.RateLimitError, which is what the check keys on."""


def state(rating="Hold", decision=None, **reports):
    return {
        "final_rating": rating,
        "final_trade_decision": decision or (
            "**Rating**: Hold\n\n**Executive Summary**: Demand is strong. Supply is tight. "
            "Valuation is rich.\n\n**Investment Thesis**: ..."
        ),
        "market_report": reports.get("market", "Uptrend; RSI 61."),
        "news_report": reports.get("news", "Revenue rose 56% year over year."),
        "fundamentals_report": reports.get("fundamentals", "Net margin 55%."),
    }


class FakeGraph:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def propagate(self, ticker, trade_date):
        self.calls.append((ticker, trade_date))
        outcome = self.script[ticker]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome, outcome["final_rating"]


def fields(**overrides):
    base = dict(score=70, trend="bullish", sentiment="Positive.", earnings_outlook="Growing.",
                risks=["Valuation stretched."], catalysts=["Revenue rose 56%."], latest="Launch.")
    base.update(overrides)
    return ExtractedFields(**base)


def run(script, extractor_results=None, tickers=None):
    graph = FakeGraph(script)
    results = list(extractor_results or [])
    prompts = []

    def extractor(prompt):
        prompts.append(prompt)
        return results.pop(0) if results else fields()

    report, calls = run_dashboard(
        tickers or list(script), SESSION, NOW,
        graph_factory=lambda: graph, extractor=extractor,
        identity=lambda t: {"company_name": f"{t} Corp"},
    )
    return report, graph, prompts


def test_happy_path_entry_fields():
    report, graph, _ = run({"NVDA": state("Hold")})
    entry = report.entries[0]
    assert (entry.ticker, entry.name, entry.rating, entry.verdict) == ("NVDA", "NVDA Corp", "Hold", "watch")
    assert entry.score == 64  # 70 clamped into Hold's 45-64 band
    assert entry.trend == "bullish"
    assert entry.catalysts == ["Revenue rose 56%."]
    assert graph.calls == [("NVDA", "2026-10-05")]
    assert report.session_date == SESSION and report.generated_at == NOW


def test_review_signal_becomes_review_entry():
    report, _, prompts = run({"NVDA": state("REVIEW")})
    entry = report.entries[0]
    assert entry.verdict == "review"
    assert entry.note.startswith("No readable rating")
    assert prompts == []


def test_bad_ticker_exception_is_review_and_run_continues():
    report, graph, _ = run({"NVDAA": ValueError("No data"), "AAPL": state("Buy")})
    assert report.entries[0].verdict == "review"
    assert report.entries[0].note == "Analysis failed: ValueError: No data"
    assert report.entries[0].name == "NVDAA Corp"
    assert report.entries[1].verdict == "buy"
    assert len(graph.calls) == 2


def test_quota_error_skips_remaining():
    report, graph, _ = run({"A": state("Buy"), "B": RateLimitError("429"), "C": state("Sell")})
    assert [e.verdict for e in report.entries] == ["buy", "skipped", "skipped"]
    assert report.entries[2].note == "daily model quota reached"
    assert [c[0] for c in graph.calls] == ["A", "B"]


def test_quota_error_in_extractor_skips_remaining():
    graph = FakeGraph({"A": state("Buy"), "B": state("Buy")})

    def extractor(prompt):
        raise RateLimitError("429")

    report, _ = run_dashboard(["A", "B"], SESSION, NOW, graph_factory=lambda: graph,
                              extractor=extractor, identity=lambda t: {})
    assert [e.verdict for e in report.entries] == ["skipped", "skipped"]
    assert report.entries[0].name == "A"


def test_extractor_retry_then_fallback():
    report, _, prompts = run({"NVDA": state("Buy")}, extractor_results=[None, None])
    entry = report.entries[0]
    assert len(prompts) == 2
    assert (entry.verdict, entry.rating, entry.score, entry.trend) == ("buy", "Buy", None, None)
    assert entry.note == "Demand is strong. Supply is tight."


def test_extractor_second_try_succeeds():
    report, _, prompts = run({"NVDA": state("Buy")}, extractor_results=[None, fields(score=90)])
    assert len(prompts) == 2
    assert report.entries[0].score == 90


def test_ungrounded_risk_dropped():
    report, _, _ = run({"NVDA": state("Hold")},
                       extractor_results=[fields(risks=["Debt up 99.9%", "Competition."])])
    assert report.entries[0].risks == ["Competition."]


def test_is_quota_error_walks_cause_chain():
    try:
        try:
            raise RateLimitError("429")
        except RateLimitError as inner:
            raise RuntimeError("graph node failed") from inner
    except RuntimeError as outer:
        assert is_quota_error(outer)
    assert not is_quota_error(ValueError("x"))


def test_is_quota_error_status_code():
    exc = Exception("too many")
    exc.status_code = 429
    assert is_quota_error(exc)


def test_selected_analysts_default_and_social():
    assert selected_analysts({}) == ("market", "news", "fundamentals")
    assert selected_analysts({"DAILY_ANALYSTS": "market, social"}) == ("market", "social")


def test_selected_analysts_unknown_raises():
    with pytest.raises(ValueError, match="sentiment"):
        selected_analysts({"DAILY_ANALYSTS": "market,sentiment"})


def test_lean_config_values():
    config = lean_config({"DAILY_LLM_MAX_RETRIES": "9"})
    assert config["max_debate_rounds"] == 1
    assert config["max_risk_discuss_rounds"] == 1
    assert config["output_language"] == "English"
    assert config["llm_max_retries"] == 9
    assert lean_config({})["llm_max_retries"] == 6


def test_extract_prompt_truncates_reports():
    long = "x" * 10_000
    prompt = extract_prompt(state(market=long), ("market", "news"))
    assert "x" * 6000 in prompt and "x" * 6001 not in prompt
    assert "Revenue rose 56%" in prompt          # news report included
    assert "Net margin 55%" not in prompt        # fundamentals not selected
    assert "Hold: 45-64" in prompt               # rubric present
