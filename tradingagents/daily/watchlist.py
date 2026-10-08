"""Read the dashboard watchlist: one ticker per line, ``#`` starts a comment."""

from __future__ import annotations

import re
from pathlib import Path

from tradingagents.dataflows.symbols import normalize_symbol

MAX_TICKERS = 15

_TICKER_RE = re.compile(r"^[A-Z0-9.\-^=]{1,15}$")


class WatchlistError(ValueError):
    """The watchlist file cannot be used as written."""


def load_watchlist(path: Path) -> list[str]:
    """Return the watchlist's tickers in file order, without duplicates.

    ``utf-8-sig`` drops the byte-order mark Windows editors add, and
    ``splitlines`` treats CRLF like LF, so a file saved anywhere reads the same.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    tickers: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        raw = line.split("#", 1)[0].strip()
        if not raw:
            continue
        ticker = normalize_symbol(raw)
        if not _TICKER_RE.match(ticker):
            raise WatchlistError(f"{path}: line {number}: not a ticker: {raw!r}")
        if ticker not in tickers:
            tickers.append(ticker)
    if not tickers:
        raise WatchlistError(f"{path}: no tickers")
    if len(tickers) > MAX_TICKERS:
        raise WatchlistError(
            f"{path}: {len(tickers)} tickers; the limit is {MAX_TICKERS}"
        )
    return tickers
