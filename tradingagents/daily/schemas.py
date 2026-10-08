"""Data shapes for the daily Telegram dashboard and market recap."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Verdict = Literal["buy", "watch", "sell", "review", "skipped"]
Trend = Literal["bullish", "range_bound", "bearish"]

MAX_LIST_ITEMS = 3


class DashboardEntry(BaseModel):
    """One stock's line and message on the dashboard."""

    ticker: str
    name: str
    rating: str
    verdict: Verdict
    score: int | None = None
    trend: Trend | None = None
    sentiment: str = ""
    earnings_outlook: str = ""
    risks: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    latest: str = ""
    note: str | None = None


class ExtractedFields(BaseModel):
    """What the extractor model fills in from a finished analysis."""

    score: int = Field(
        ge=0, le=100,
        description="Conviction score 0-100, inside the band for the decision's rating.",
    )
    trend: Trend = Field(description="Price trend from the market report.")
    sentiment: str = Field(description="Market sentiment toward the stock, at most two sentences.")
    earnings_outlook: str = Field(
        description="Earnings and fundamentals outlook, at most two sentences.",
    )
    risks: list[str] = Field(
        description="Up to three concrete risks, each one sentence, using only figures stated in the reports.",
    )
    catalysts: list[str] = Field(
        description="Up to three concrete positive catalysts, each one sentence, using only figures stated in the reports.",
    )
    latest: str = Field(description="The most important recent news, at most two sentences.")

    # A fourth risk is not worth a failed call and a retry: keep the first three.
    @field_validator("risks", "catalysts", mode="before")
    @classmethod
    def _first_three(cls, value):
        if isinstance(value, list):
            return value[:MAX_LIST_ITEMS]
        return value


class DashboardReport(BaseModel):
    session_date: date
    generated_at: datetime
    entries: list[DashboardEntry]


class IndexQuote(BaseModel):
    name: str
    close: float
    pct_change: float


class MarketRecap(BaseModel):
    session_date: date
    indices: list[IndexQuote]
    advancers: int
    decliners: int
    new_highs: int
    new_lows: int
    covered: int
    total: int
    leading: list[str]
    lagging: list[str]
