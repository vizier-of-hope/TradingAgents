"""Watchlist file parsing for the daily dashboard."""

import pytest

from tradingagents.daily.watchlist import MAX_TICKERS, WatchlistError, load_watchlist


def test_parses_comments_blanks_case_and_duplicates(tmp_path):
    p = tmp_path / "w.txt"
    p.write_text("# mine\nnvda\n\n  AAPL  # core\nNVDA\n", encoding="utf-8")
    assert load_watchlist(p) == ["NVDA", "AAPL"]


def test_bom_and_crlf_parse_like_clean_file(tmp_path):
    p = tmp_path / "w.txt"
    p.write_bytes("﻿NVDA\r\nAAPL \r\n".encode("utf-8"))
    assert load_watchlist(p) == ["NVDA", "AAPL"]


def test_more_than_15_is_error(tmp_path):
    p = tmp_path / "w.txt"
    p.write_text("\n".join(f"T{i}" for i in range(MAX_TICKERS + 1)), encoding="utf-8")
    with pytest.raises(WatchlistError, match="16"):
        load_watchlist(p)


def test_invalid_ticker_names_line(tmp_path):
    p = tmp_path / "w.txt"
    p.write_text("NVDA\nbad ticker!\n", encoding="utf-8")
    with pytest.raises(WatchlistError, match="line 2"):
        load_watchlist(p)


def test_empty_is_error(tmp_path):
    p = tmp_path / "w.txt"
    p.write_text("# nothing\n", encoding="utf-8")
    with pytest.raises(WatchlistError):
        load_watchlist(p)
