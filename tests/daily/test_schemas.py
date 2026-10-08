"""Schema rules the daily dashboard relies on."""

from tradingagents.daily.schemas import ExtractedFields


def test_extracted_lists_keep_first_three():
    fields = ExtractedFields(
        score=50, trend="bullish", sentiment="s", earnings_outlook="e", latest="l",
        risks=["r1", "r2", "r3", "r4"], catalysts=["c1", "c2", "c3", "c4", "c5"],
    )
    assert fields.risks == ["r1", "r2", "r3"]
    assert fields.catalysts == ["c1", "c2", "c3"]
