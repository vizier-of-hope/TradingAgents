"""Telegram Bot API sender: splitting and retries, with HTTP faked."""

import pytest

from tradingagents.daily.telegram import TelegramError, send, split_message

TOKEN = "123:secret-token"


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, statuses):
        self.responses = list(statuses)
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json))
        status, body = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return FakeResponse(status, body)


def test_split_on_line_boundaries():
    text = "\n".join(["x" * 100] * 50)
    parts = split_message(text)
    assert len(parts) == 2
    assert all(len(p) <= 4096 for p in parts)
    assert "\n".join(parts) == text


def test_single_overlong_line_hard_split():
    parts = split_message("y" * 9000)
    assert [len(p) for p in parts] == [4096, 4096, 808]


def test_limit_counts_utf16_units_for_emoji():
    # Each 🟢 is 2 UTF-16 code units, which is how Telegram measures length.
    parts = split_message("🟢" * 2100)
    assert len(parts) == 2
    assert all(len(p.encode("utf-16-le")) // 2 <= 4096 for p in parts)
    assert "".join(parts) == "🟢" * 2100


def test_short_message_unchanged():
    assert split_message("hello") == ["hello"]


def test_send_posts_each_part_in_order():
    session = FakeSession([(200, {"ok": True})])
    send(["one", "two"], TOKEN, "42", session=session, sleep=lambda s: None)
    assert [c[1]["text"] for c in session.calls] == ["one", "two"]
    assert session.calls[0][0] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert session.calls[0][1]["chat_id"] == "42"


def test_retry_after_429_honours_retry_after():
    session = FakeSession([(429, {"parameters": {"retry_after": 3}}), (200, {"ok": True})])
    slept = []
    send(["one"], TOKEN, "42", session=session, sleep=slept.append)
    assert slept == [3]
    assert len(session.calls) == 2


def test_gives_up_after_5_attempts():
    session = FakeSession([(500, {})])
    slept = []
    with pytest.raises(TelegramError):
        send(["one"], TOKEN, "42", session=session, sleep=slept.append)
    assert len(session.calls) == 5
    assert len(slept) == 4


def test_client_error_not_retried():
    session = FakeSession([(400, {"description": "Bad Request: chat not found"})])
    with pytest.raises(TelegramError, match="chat not found"):
        send(["one"], TOKEN, "42", session=session, sleep=lambda s: None)
    assert len(session.calls) == 1


def test_token_not_in_error_message():
    session = FakeSession([(500, {})])
    with pytest.raises(TelegramError) as info:
        send(["one"], TOKEN, "42", session=session, sleep=lambda s: None)
    assert TOKEN not in str(info.value)
