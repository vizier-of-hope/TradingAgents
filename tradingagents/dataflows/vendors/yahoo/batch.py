"""Daily bars for many symbols in one Yahoo request, for market-wide summaries."""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from .common import yf_retry


def download_batch(tickers: list[str], *, start, end) -> pd.DataFrame:
    """Daily OHLCV for ``tickers`` from ``start`` up to (not including) ``end``.

    Columns are ``(field, ticker)``. Rate limits are retried and other
    failures raised as ``VendorUnavailableError``; an empty answer is an
    empty frame.
    """
    df = yf_retry(lambda: yf.download(
        list(tickers), start=start, end=end, group_by="column",
        auto_adjust=False, progress=False, threads=True,
    ))
    return df if df is not None else pd.DataFrame()
