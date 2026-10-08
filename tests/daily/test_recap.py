"""Market recap numbers from yfinance-shaped DataFrames, no network."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.daily.recap import (
    INDICES,
    SECTORS,
    RecapDataError,
    breadth,
    build_recap,
    index_quotes,
    load_members,
    rank_sectors,
)

SESSION = date(2026, 10, 5)


def frame(fields: dict[str, dict[str, list[float]]], end=SESSION) -> pd.DataFrame:
    """yf.download(group_by="column") shape: columns (field, ticker), dated rows ending at ``end``."""
    n = len(next(iter(next(iter(fields.values())).values())))
    index = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    columns = {(field, t): values for field, by_ticker in fields.items() for t, values in by_ticker.items()}
    return pd.DataFrame(columns, index=index)


def closes(by_ticker):
    return frame({"Close": by_ticker})


def test_index_quotes_pct_change():
    df = closes({"^GSPC": [100.0, 101.5], "^IXIC": [200.0, 198.0], "^DJI": [50.0, 50.0]})
    quotes = index_quotes(df, SESSION)
    assert [q.name for q in quotes] == ["S&P 500", "Nasdaq", "Dow"]
    assert quotes[0].close == 101.5
    assert quotes[0].pct_change == pytest.approx(1.5)
    assert quotes[1].pct_change == pytest.approx(-1.0)


def test_missing_index_raises():
    df = closes({"^GSPC": [100.0, 101.0], "^IXIC": [200.0, 201.0], "^DJI": [np.nan, np.nan]})
    with pytest.raises(RecapDataError, match="Dow"):
        index_quotes(df, SESSION)


def test_session_date_missing_raises():
    df = closes({"^GSPC": [100.0, 101.0], "^IXIC": [1.0, 1.0], "^DJI": [1.0, 1.0]})
    with pytest.raises(RecapDataError, match="2026-10-06"):
        index_quotes(df, date(2026, 10, 6))


def _member_frame(close_by_ticker):
    return frame({
        "Close": close_by_ticker,
        "High": dict(close_by_ticker.items()),
        "Low": dict(close_by_ticker.items()),
    })


def test_breadth_counts_and_ties():
    df = _member_frame({"A": [10.0, 11.0], "B": [10.0, 9.0], "C": [10.0, 10.0]})
    adv, dec, _, _, covered = breadth(df, SESSION)
    assert (adv, dec, covered) == (1, 1, 3)


def test_breadth_nan_last_row_is_missing_not_unchanged():
    df = _member_frame({"A": [10.0, 11.0], "D": [10.0, np.nan]})
    adv, dec, _, _, covered = breadth(df, SESSION)
    assert (adv, dec, covered) == (1, 0, 1)


def test_52w_high_and_low():
    # Prior year trades between 9 and 11; E breaks above, F below, G stays inside.
    close, high, low = [10.0] * 251, [11.0] * 251, [9.0] * 251
    df = frame({
        "Close": {"E": close + [12.0], "F": close + [8.0], "G": close + [10.0]},
        "High": {"E": high + [12.0], "F": high + [9.0], "G": high + [10.5]},
        "Low": {"E": low + [11.0], "F": low + [8.0], "G": low + [9.5]},
    })
    _, _, highs, lows, _ = breadth(df, SESSION)
    assert (highs, lows) == (1, 1)


def test_52w_low_counts_equal_to_prior_min():
    # Matching the year's low counts as a new low (spec: session low <= prior min).
    flat = [10.0] * 251
    df = frame({
        "Close": {"G": flat + [10.0]},
        "High": {"G": flat + [10.0]},
        "Low": {"G": flat + [10.0]},
    })
    _, _, highs, lows, _ = breadth(df, SESSION)
    assert (highs, lows) == (1, 1)


def test_rank_sectors_top3_bottom3():
    tickers = list(SECTORS)
    moves = {t: [100.0, 100.0 + i] for i, t in enumerate(tickers)}  # XLK +0 ... XLC +10
    leading, lagging = rank_sectors(closes(moves), SESSION)
    assert leading == [SECTORS["XLC"], SECTORS["XLRE"], SECTORS["XLB"]]
    assert lagging == [SECTORS["XLK"], SECTORS["XLF"], SECTORS["XLV"]]


def test_load_members_has_sp500():
    members = load_members()
    assert len(members) > 490
    assert "AAPL" in members and "BRK-B" in members


def test_build_recap_uses_injected_download():
    members = ["A", "B"]
    calls = []

    def fake_download(tickers, **kwargs):
        calls.append(sorted(tickers))
        if set(tickers) == set(INDICES):
            return closes({t: [100.0, 101.0] for t in INDICES})
        if set(tickers) == set(SECTORS):
            return closes({t: [100.0, 100.0 + i] for i, t in enumerate(SECTORS)})
        return _member_frame({"A": [10.0, 11.0], "B": [10.0, 9.0]})

    recap = build_recap(SESSION, download=fake_download, members=members)
    assert len(calls) == 3
    assert (recap.advancers, recap.decliners, recap.covered, recap.total) == (1, 1, 2, 2)
    assert recap.session_date == SESSION
    assert recap.indices[0].name == "S&P 500"
    assert recap.leading[0] == SECTORS["XLC"]
