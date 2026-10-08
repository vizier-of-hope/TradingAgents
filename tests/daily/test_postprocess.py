"""Rules applied in code to the extractor's output."""

import pytest

from tradingagents.daily.postprocess import clamp_score, grounded, verdict_for


@pytest.mark.parametrize("rating,verdict", [
    ("Buy", "buy"), ("Overweight", "buy"), ("Hold", "watch"),
    ("Underweight", "sell"), ("Sell", "sell"), ("REVIEW", "review"),
])
def test_verdict_for(rating, verdict):
    assert verdict_for(rating) == verdict


def test_clamp_inside_band_unchanged():
    assert clamp_score("Hold", 50) == 50


def test_clamp_above_band():
    assert clamp_score("Hold", 70) == 64


def test_clamp_below_band():
    assert clamp_score("Buy", 40) == 80


def test_grounded_keeps_items_without_numbers():
    assert grounded(["Strong AI demand"], "") == ["Strong AI demand"]


def test_grounded_drops_absent_number():
    assert grounded(["Revenue up 407.52%"], "revenue grew 40%") == []


def test_grounded_accepts_format_variants():
    src = "Net outflow of $1,234.5M; margin fell -12.5%"
    items = ["Outflow 1234.5M", "Margin down 12.5%"]
    assert grounded(items, src) == items


def test_grounded_word_units_match_letters():
    assert grounded(["Buyback of $5B"], "a 5 billion dollar buyback") == ["Buyback of $5B"]


def test_grounded_unit_must_match():
    assert grounded(["Cash $3.6B"], "cash of $3.6M") == []


def test_grounded_keeps_order_and_filters_each_item():
    src = "Q3 revenue 12% higher"
    assert grounded(["Revenue up 12%", "Margin 30%", "New CEO"], src) == ["Revenue up 12%", "New CEO"]
