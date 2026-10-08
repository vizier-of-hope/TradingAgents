"""Run a lean TradingAgents analysis per watchlist stock and condense it for Telegram."""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from tradingagents.agents.context import resolve_instrument_identity
from tradingagents.agents.rating import RATING_REVIEW
from tradingagents.dataflows.vendors.yahoo.batch import download_batch
from tradingagents.default_config import build_default_config

from .postprocess import SCORE_BANDS, clamp_score, grounded, verdict_for
from .schemas import DashboardEntry, DashboardReport, ExtractedFields

logger = logging.getLogger(__name__)

DEFAULT_ANALYSTS = ("market", "news", "fundamentals")
# Analyst key -> the state field holding its report. "social" is this repo's
# name for the sentiment analyst.
REPORT_KEYS = {
    "market": "market_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
    "social": "sentiment_report",
}
REPORT_BUDGET = 6000
EXTRACT_ATTEMPTS = 2
QUOTA_NOTE = "daily model quota reached"
RATE_LIMIT_PAUSE = 60  # seconds to wait out a per-minute limit before retrying a stock once


class CallCounter(BaseCallbackHandler):
    """Counts LLM requests per model across a run, for sizing against provider caps."""

    def __init__(self) -> None:
        self.by_model: dict[str, int] = {}

    def _record(self, kwargs: dict) -> None:
        params = kwargs.get("invocation_params") or {}
        model = params.get("model") or params.get("model_name") or "unknown"
        self.by_model[model] = self.by_model.get(model, 0) + 1

    def on_llm_start(self, *args: Any, **kwargs: Any) -> None:
        self._record(kwargs)

    def on_chat_model_start(self, *args: Any, **kwargs: Any) -> None:
        self._record(kwargs)


def lean_config(env: Mapping[str, str] = os.environ) -> dict:
    config = build_default_config()
    config.update(
        max_debate_rounds=1,
        max_risk_discuss_rounds=1,
        output_language="English",
        llm_max_retries=int(env.get("DAILY_LLM_MAX_RETRIES", "6")),
    )
    return config


def selected_analysts(env: Mapping[str, str] = os.environ) -> tuple[str, ...]:
    raw = env.get("DAILY_ANALYSTS", "")
    names = tuple(n.strip() for n in raw.split(",") if n.strip()) or DEFAULT_ANALYSTS
    unknown = [n for n in names if n not in REPORT_KEYS]
    if unknown:
        raise ValueError(
            f"DAILY_ANALYSTS has unknown analysts {unknown}; choose from {sorted(REPORT_KEYS)}"
        )
    return names


def is_quota_error(exc: BaseException) -> bool:
    """True when ``exc`` or anything it was raised from is a rate-limit (HTTP 429)."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ == "RateLimitError" or getattr(current, "status_code", None) == 429:
            return True
        current = current.__cause__ or current.__context__
    return False


def has_market_data(ticker: str, session_date: date, download: Callable[..., Any] = download_batch) -> bool:
    """Whether Yahoo has any close for ``ticker`` in the ten days to ``session_date``.

    The analysis does not fail on an unknown ticker: its tools report "no data"
    and the decision comes out as a Hold, so a typo is caught here instead.
    """
    df = download([ticker], start=session_date - timedelta(days=10), end=session_date + timedelta(days=1))
    if df.empty or "Close" not in df:
        return False
    return bool(df["Close"].notna().to_numpy().any())


def _analysis_text(final_state: Mapping[str, Any], analysts: tuple[str, ...], budget: int) -> str:
    """The decision and reports the extractor sees, truncated: the grounding source."""
    reports = "\n\n".join(
        f"## {name.title()} report\n{str(final_state.get(REPORT_KEYS[name]) or '(none)')[:budget]}"
        for name in analysts
    )
    return (
        f"# Final rating\n{final_state.get('final_rating', '')}\n\n"
        f"# Final decision\n{str(final_state.get('final_trade_decision', ''))[:budget]}\n\n"
        f"{reports}"
    )


def extract_prompt(final_state: Mapping[str, Any], analysts: tuple[str, ...], budget: int = REPORT_BUDGET) -> str:
    bands = "\n".join(f"- {rating}: {low}-{high}" for rating, (low, high) in SCORE_BANDS.items())
    return (
        "Condense this finished stock analysis into a short dashboard entry.\n"
        "Use only facts stated below. Copy every figure exactly as it appears; "
        "do not compute or invent numbers.\n\n"
        "Score the conviction from 0 to 100, inside the band for the final rating:\n"
        f"{bands}\n\n"
        f"{_analysis_text(final_state, analysts, budget)}"
    )


_SUMMARY_RE = re.compile(r"\*\*Executive Summary\*\*\s*:\s*(.+)")


def _summary(decision: str) -> str:
    """First two sentences of the decision's executive summary, else of the decision."""
    match = _SUMMARY_RE.search(decision)
    if match:
        text = match.group(1)
    else:
        lines = (line.strip() for line in decision.splitlines())
        text = " ".join(line for line in lines if line and not line.startswith(("#", "**Rating")))
    return " ".join(re.split(r"(?<=[.!?])\s+", text.strip())[:2])


def build_extractor(llm: Any) -> Callable[[str], ExtractedFields | None]:
    # Force the tool call: the OpenAI-compatible client leaves tool_choice unset
    # for local servers, and a model that answers in prose yields no fields.
    structured = llm.with_structured_output(ExtractedFields, tool_choice="ExtractedFields")

    def extract(prompt: str) -> ExtractedFields | None:
        try:
            return structured.invoke(prompt)
        except Exception as exc:
            if is_quota_error(exc):
                raise
            logger.warning("dashboard extractor failed: %s", exc)
            return None

    return extract


def _default_extractor(config: dict, counter: CallCounter) -> Callable[[str], ExtractedFields | None]:
    from tradingagents.llm_clients import create_tier_client

    return build_extractor(create_tier_client(config, "quick", callbacks=[counter]).get_llm())


def _analyse(ticker, name, graph, extractor, analysts, trade_date) -> DashboardEntry:
    final_state, signal = graph.propagate(ticker, trade_date)
    if signal == RATING_REVIEW:
        return DashboardEntry(ticker=ticker, name=name, rating=signal, verdict="review",
                              note="No readable rating in the final decision")
    verdict = verdict_for(signal)
    prompt = extract_prompt(final_state, analysts)
    fields = None
    for _ in range(EXTRACT_ATTEMPTS):
        fields = extractor(prompt)
        if fields is not None:
            break
    if fields is None:
        return DashboardEntry(ticker=ticker, name=name, rating=signal, verdict=verdict,
                              note=_summary(str(final_state.get("final_trade_decision", ""))))
    source = _analysis_text(final_state, analysts, REPORT_BUDGET)  # not the rubric's numbers
    return DashboardEntry(
        ticker=ticker, name=name, rating=signal, verdict=verdict,
        score=clamp_score(signal, fields.score), trend=fields.trend,
        sentiment=fields.sentiment, earnings_outlook=fields.earnings_outlook,
        risks=grounded(fields.risks, source), catalysts=grounded(fields.catalysts, source),
        latest=fields.latest,
    )


def run_dashboard(
    tickers: list[str],
    session_date: date,
    now_utc: datetime,
    *,
    graph_factory: Callable[[], Any] | None = None,
    extractor: Callable[[str], ExtractedFields | None] | None = None,
    identity: Callable[[str], dict] = resolve_instrument_identity,
    env: Mapping[str, str] = os.environ,
    has_data: Callable[[str, date], bool] = has_market_data,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[DashboardReport, dict[str, int]]:
    """Analyse ``tickers`` one at a time; return the report and LLM calls per model.

    A rate limit (HTTP 429) still failing after the client's retries may be a
    per-minute limit: wait ``RATE_LIMIT_PAUSE`` and retry the stock once. A
    second one is taken as the daily quota, and the remaining stocks are skipped.
    """
    analysts = selected_analysts(env)
    counter = CallCounter()
    if graph_factory is None or extractor is None:
        config = lean_config(env)
    if graph_factory is None:
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        def graph_factory():
            return TradingAgentsGraph(selected_analysts=analysts, config=config, callbacks=[counter])
    if extractor is None:
        extractor = _default_extractor(config, counter)

    graph = graph_factory()
    trade_date = session_date.isoformat()
    entries: list[DashboardEntry] = []
    quota_hit = False
    for ticker in tickers:
        name = identity(ticker).get("company_name") or ticker
        if quota_hit:
            entries.append(DashboardEntry(ticker=ticker, name=name, rating="", verdict="skipped", note=QUOTA_NOTE))
            continue
        if not has_data(ticker, session_date):
            entries.append(DashboardEntry(ticker=ticker, name=name, rating=RATING_REVIEW, verdict="review",
                                          note=f"No market data for {ticker} (mistyped or delisted?)"))
            continue
        try:
            try:
                entries.append(_analyse(ticker, name, graph, extractor, analysts, trade_date))
            except Exception as exc:
                if not is_quota_error(exc):
                    raise
                logger.warning("rate limited on %s; retrying in %ss", ticker, RATE_LIMIT_PAUSE)
                sleep(RATE_LIMIT_PAUSE)
                entries.append(_analyse(ticker, name, graph, extractor, analysts, trade_date))
        except Exception as exc:
            if is_quota_error(exc):
                quota_hit = True
                entries.append(DashboardEntry(ticker=ticker, name=name, rating="", verdict="skipped", note=QUOTA_NOTE))
            else:
                logger.exception("analysis of %s failed", ticker)
                entries.append(DashboardEntry(ticker=ticker, name=name, rating=RATING_REVIEW, verdict="review",
                                              note=f"Analysis failed: {type(exc).__name__}: {exc}"))
    report = DashboardReport(session_date=session_date, generated_at=now_utc, entries=entries)
    return report, counter.by_model
