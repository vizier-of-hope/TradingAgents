"""Rules applied in code to a finished analysis, so the model cannot bend them."""

from __future__ import annotations

import re

from tradingagents.agents.rating import RATING_REVIEW

from .schemas import Verdict

_VERDICTS: dict[str, Verdict] = {
    "Buy": "buy", "Overweight": "buy", "Hold": "watch",
    "Underweight": "sell", "Sell": "sell",
}

SCORE_BANDS: dict[str, tuple[int, int]] = {
    "Buy": (80, 100),
    "Overweight": (65, 79),
    "Hold": (45, 64),
    "Underweight": (30, 44),
    "Sell": (0, 29),
}

# A figure: optional $ and sign, digits with thousands separators and decimals,
# and an optional unit. Not preceded by a letter or digit, so "Q3" is no figure.
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9.])\$?-?\d[\d,]*(?:\.\d+)?(?:\s?(?:%|thousand|million|billion|[KMB]\b))?",
    re.IGNORECASE,
)
_UNIT_WORDS = {"THOUSAND": "K", "MILLION": "M", "BILLION": "B"}


def verdict_for(rating: str) -> Verdict:
    if rating == RATING_REVIEW:
        return "review"
    return _VERDICTS[rating]


def clamp_score(rating: str, score: int) -> int:
    low, high = SCORE_BANDS[rating]
    return min(max(score, low), high)


def _normalize(token: str) -> str:
    token = re.sub(r"[\s$,]", "", token).lstrip("-").upper()
    for word, letter in _UNIT_WORDS.items():
        token = token.replace(word, letter)
    return token


def _figures(text: str) -> set[str]:
    return {_normalize(m.group()) for m in _NUMBER_RE.finditer(text)}


def grounded(items: list[str], source: str) -> list[str]:
    """Keep the items whose every figure also appears in ``source``.

    Formatting is ignored (``$1,234.5M`` matches ``1234.5M``, ``-12.5%``
    matches ``12.5%``) but units are not (``$3.6B`` does not match ``$3.6M``).
    """
    known = _figures(source)
    return [item for item in items if _figures(item) <= known]
