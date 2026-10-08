"""Batched Yahoo download used by the market recap."""

import inspect

import pandas as pd

from tradingagents.daily import recap
from tradingagents.dataflows.vendors.yahoo import batch


def test_download_batch_passes_column_layout(monkeypatch):
    seen = {}

    def fake_download(tickers, **kwargs):
        seen.update(kwargs, tickers=tickers)
        return pd.DataFrame({"x": [1]})

    monkeypatch.setattr(batch.yf, "download", fake_download)
    df = batch.download_batch(["A", "B"], start="2026-01-01", end="2026-01-05")
    assert list(df["x"]) == [1]
    assert seen["tickers"] == ["A", "B"]
    assert seen["group_by"] == "column" and seen["auto_adjust"] is False
    assert seen["start"] == "2026-01-01" and seen["end"] == "2026-01-05"


def test_empty_answer_is_empty_frame(monkeypatch):
    monkeypatch.setattr(batch, "yf_retry", lambda func: None)
    assert batch.download_batch(["A"], start="2026-01-01", end="2026-01-05").empty


def test_recap_downloads_through_data_layer():
    assert inspect.signature(recap.build_recap).parameters["download"].default is batch.download_batch
