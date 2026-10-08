"""Send plain-text messages through the Telegram Bot API."""

from __future__ import annotations

import time
from collections.abc import Callable

import requests

LIMIT = 4096
MAX_ATTEMPTS = 5
_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramError(RuntimeError):
    """A message could not be delivered."""


def _units(text: str) -> int:
    # Telegram measures message length in UTF-16 code units: an emoji counts 2.
    return len(text.encode("utf-16-le")) // 2


def _hard_split(line: str, limit: int) -> list[str]:
    chunks, current, size = [], "", 0
    for char in line:
        width = _units(char)
        if size + width > limit:
            chunks.append(current)
            current, size = "", 0
        current += char
        size += width
    chunks.append(current)
    return chunks


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    """Split ``text`` into parts of at most ``limit`` units, on line breaks where possible.

    A line longer than ``limit`` on its own is cut mid-line.
    """
    parts: list[str] = []
    current: str | None = None
    for line in text.split("\n"):
        for chunk in _hard_split(line, limit):
            candidate = chunk if current is None else f"{current}\n{chunk}"
            if _units(candidate) <= limit:
                current = candidate
            else:
                parts.append(current)
                current = chunk
    parts.append(current or "")
    return parts


def _post(session, token: str, chat_id: str, text: str, sleep: Callable[[float], None]) -> None:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = session.post(
            _URL.format(token=token),
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=30,
        )
        if response.status_code == 200:
            return
        try:
            body = response.json()
        except ValueError:
            body = {}
        retryable = response.status_code == 429 or response.status_code >= 500
        if not retryable or attempt == MAX_ATTEMPTS:
            # Never include the URL: it carries the bot token.
            raise TelegramError(
                f"Telegram sendMessage failed with HTTP {response.status_code}: "
                f"{body.get('description', 'no description')}"
            )
        sleep(body.get("parameters", {}).get("retry_after") or 2 ** attempt)


def send(
    texts: list[str],
    token: str,
    chat_id: str,
    *,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Send each text in order, splitting any that exceed Telegram's limit."""
    session = session or requests.Session()
    for text in texts:
        for part in split_message(text):
            _post(session, token, chat_id, part, sleep)
