"""python -m tradingagents.daily {dashboard,recap} [--dry-run] [--date YYYY-MM-DD]"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from . import dashboard, market_clock, recap, telegram, watchlist
from .render import render_dashboard, render_failure, render_recap

SEPARATOR = "=" * 40


@dataclass
class Deps:
    send: Callable = telegram.send
    run_dashboard: Callable = dashboard.run_dashboard
    build_recap: Callable = recap.build_recap
    session_for: Callable = market_clock.session_for
    load_watchlist: Callable = watchlist.load_watchlist


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m tradingagents.daily")
    parser.add_argument("job", choices=["dashboard", "recap"])
    parser.add_argument("--dry-run", action="store_true", help="print the messages instead of sending them")
    parser.add_argument("--date", type=date.fromisoformat, help="US session date to report on (YYYY-MM-DD)")
    parser.add_argument("--watchlist", type=Path, default=Path("watchlist.txt"))
    return parser.parse_args(argv)


def _messages(args, session_date: date, now_utc: datetime, deps: Deps) -> list[str]:
    if args.job == "recap":
        return [render_recap(deps.build_recap(session_date))]
    tickers = deps.load_watchlist(args.watchlist)
    report, calls = deps.run_dashboard(tickers, session_date, now_utc)
    per_model = ", ".join(f"{model}: {n}" for model, n in sorted(calls.items()))
    print(f"LLM calls: {sum(calls.values())} ({per_model})")
    return render_dashboard(report)


def main(
    argv: list[str] | None = None,
    *,
    now_utc: datetime | None = None,
    env: Mapping[str, str] = os.environ,
    deps: Deps | None = None,
) -> int:
    args = _parse_args(argv)
    deps = deps or Deps()
    now_utc = now_utc or datetime.now(UTC)
    token, chat_id = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not args.dry_run and not (token and chat_id):
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (or use --dry-run).", file=sys.stderr)
        return 2

    session_date = args.date or deps.session_for(args.job, now_utc)
    if session_date is None:
        print("No US session to report; nothing sent.")
        return 0

    try:
        messages = _messages(args, session_date, now_utc, deps)
        if args.dry_run:
            print(f"\n{SEPARATOR}\n".join(messages))
        else:
            deps.send(messages, token, chat_id)
    except Exception as exc:
        if token and chat_id and not args.dry_run:
            notice = render_failure(args.job, exc).replace(token, "***")
            try:
                deps.send([notice], token, chat_id)
            except Exception as notice_exc:  # the original failure matters more
                print(f"Could not send the failure notice: {notice_exc}", file=sys.stderr)
        raise
    return 0


if __name__ == "__main__":
    # Emoji in the messages need UTF-8 even on a Windows console.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
