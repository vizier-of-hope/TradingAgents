"""US market recap from yfinance: indices, S&P 500 breadth, sector ETFs. No LLM."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from importlib.resources import files

import pandas as pd

from tradingagents.dataflows.vendors.yahoo.batch import download_batch

from .schemas import IndexQuote, MarketRecap

INDICES = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow"}
SECTORS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}
LOOKBACK_SESSIONS = 251  # prior sessions a 52-week high or low is measured against
TOP_N = 3


class RecapDataError(RuntimeError):
    """The data needed for an accurate recap is missing."""


def load_members() -> list[str]:
    text = (files("tradingagents.daily") / "data" / "sp500.txt").read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _session_pos(df: pd.DataFrame, session_date: date) -> int:
    """Position of the session row in ``df``; raises when the session is absent."""
    dates = pd.DatetimeIndex(df.index).normalize()
    matches = (dates == pd.Timestamp(session_date)).nonzero()[0]
    if len(matches) == 0 or matches[0] == 0:
        raise RecapDataError(f"no data for session {session_date.isoformat()} and the session before it")
    return int(matches[0])


def _pct_changes(close: pd.DataFrame, pos: int) -> pd.Series:
    return (close.iloc[pos] / close.iloc[pos - 1] - 1.0) * 100.0


def index_quotes(df: pd.DataFrame, session_date: date) -> list[IndexQuote]:
    pos = _session_pos(df, session_date)
    close = df["Close"]
    quotes = []
    for ticker, name in INDICES.items():
        today = close[ticker].iloc[pos] if ticker in close else float("nan")
        before = close[ticker].iloc[pos - 1] if ticker in close else float("nan")
        if pd.isna(today) or pd.isna(before):
            raise RecapDataError(f"no {name} ({ticker}) close for {session_date.isoformat()}")
        quotes.append(IndexQuote(name=name, close=float(today), pct_change=float((today / before - 1.0) * 100.0)))
    return quotes


def breadth(df: pd.DataFrame, session_date: date) -> tuple[int, int, int, int, int]:
    """(advancers, decliners, new 52-week highs, new 52-week lows, members covered).

    A member with no close on the session or the one before is not covered,
    rather than counted as unchanged.
    """
    pos = _session_pos(df, session_date)
    close, high, low = df["Close"], df["High"], df["Low"]
    change = close.iloc[pos] - close.iloc[pos - 1]
    covered = change.notna()
    prior = slice(max(0, pos - LOOKBACK_SESSIONS), pos)
    year_high = high.iloc[prior].max()
    year_low = low.iloc[prior].min()
    new_high = covered & (high.iloc[pos] >= year_high)
    new_low = covered & (low.iloc[pos] <= year_low)
    return (
        int((change[covered] > 0).sum()),
        int((change[covered] < 0).sum()),
        int(new_high.sum()),
        int(new_low.sum()),
        int(covered.sum()),
    )


def rank_sectors(df: pd.DataFrame, session_date: date) -> tuple[list[str], list[str]]:
    """Top three sectors (best first) and bottom three (worst first) by % change."""
    pos = _session_pos(df, session_date)
    changes = _pct_changes(df["Close"], pos).dropna().sort_values(ascending=False)
    names = [SECTORS[t] for t in changes.index]
    return names[:TOP_N], list(reversed(names[-TOP_N:]))


def build_recap(
    session_date: date,
    download: Callable[..., pd.DataFrame] = download_batch,
    members: list[str] | None = None,
) -> MarketRecap:
    members = members if members is not None else load_members()
    end = session_date + timedelta(days=1)  # yfinance's end date is exclusive

    def fetch(tickers, days_back):
        return download(list(tickers), start=session_date - timedelta(days=days_back), end=end)

    indices = index_quotes(fetch(INDICES, 10), session_date)
    leading, lagging = rank_sectors(fetch(SECTORS, 10), session_date)
    advancers, decliners, highs, lows, covered = breadth(fetch(members, 380), session_date)
    return MarketRecap(
        session_date=session_date, indices=indices,
        advancers=advancers, decliners=decliners, new_highs=highs, new_lows=lows,
        covered=covered, total=len(members), leading=leading, lagging=lagging,
    )
