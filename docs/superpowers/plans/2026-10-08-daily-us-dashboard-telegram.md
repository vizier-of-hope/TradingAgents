# Daily US Dashboard and Market Recap via Telegram — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two scheduled GitHub Actions jobs that send an English Decision Dashboard (watchlist analysed by a lean TradingAgents run) and a no-LLM Market Recap to Telegram.

**Architecture:** New subpackage `tradingagents/daily/` with one module per job (watchlist, clock, recap, dashboard, render, telegram) and a `python -m tradingagents.daily` entry point. Core agents and schemas are untouched; the dashboard calls `TradingAgentsGraph.propagate` then one structured extractor call. A workflow on the user's fork runs both jobs on fixed UTC crons.

**Tech Stack:** Python ≥ 3.11, pydantic, yfinance, pandas, requests, `exchange_calendars`, langchain (via existing `create_tier_client` / `bind_structured`), pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-08-daily-us-dashboard-telegram-design.md`

## Global Constraints

- Nothing outside `tradingagents/daily/`, `tests/daily/`, `.github/workflows/daily.yml`, `watchlist.txt`, `pyproject.toml` (one dependency) and `README.md` (one section) changes.
- Add exactly one runtime dependency: `exchange_calendars` (pin a floor at the version installed in Task 1).
- Messages are English, plain text (no Telegram `parse_mode`).
- Verdict mapping: Buy, Overweight → buy; Hold → watch; Underweight, Sell → sell; REVIEW → review.
- Emoji: 🟢 buy, 🟡 watch, 🔴 sell, ⚠️ review, ⏭ skipped.
- Score bands: Buy 80–100, Overweight 65–79, Hold 45–64, Underweight 30–44, Sell 0–29.
- Watchlist max 15 tickers; more is an error.
- Crons: dashboard `0 11 * * 1-5` (19:00 SGT), recap `0 22 * * 1-5` (06:00 SGT). Footer time is SGT (`Asia/Singapore`).
- Telegram message limit 4096 characters.
- Breadth coverage note shown when coverage < 95%.
- Tests never touch the network or an LLM and must pass with `TZ=America/New_York` (CI matrix); every clock function takes `now_utc` explicitly.
- The analyst key for the sentiment analyst in this repo is `social`, not `sentiment`. `DAILY_ANALYSTS` defaults to `market,news,fundamentals`.

## Review Focus

1. `watchlist.txt` saved from Windows or GitHub's web editor (UTF-8 BOM, CRLF, trailing spaces) must parse identically to a clean file — test in Task 1.
2. A mistyped or delisted ticker (e.g. `NVDAA`) must become one ⚠️ Review line, not abort the dashboard — test in Task 7.
3. A single line longer than 4096 characters (no newline to split on) must still send, hard-split — test in Task 4.
4. A breadth member whose last row is NaN (halted, not yet printed) must count as missing coverage, not as unchanged — test in Task 5.
5. Grounding must accept the same figure written differently (`$1,234.5M` vs `1234.5M`, `-12.5%` vs `12.5%`) and reject a figure that is absent — test in Task 6.

---

### Task 1: Package scaffold, schemas, watchlist

**Files:**
- Create: `tradingagents/daily/__init__.py` (empty), `tradingagents/daily/schemas.py`, `tradingagents/daily/watchlist.py`, `tests/daily/__init__.py`, `tests/daily/test_watchlist.py`
- Modify: `pyproject.toml` (add `exchange_calendars>=<installed version>` to `dependencies`)

**Interfaces:**
- Produces (in `schemas.py`, pydantic `BaseModel`s):
  - `Verdict = Literal["buy", "watch", "sell", "review", "skipped"]`
  - `Trend = Literal["bullish", "range_bound", "bearish"]`
  - `DashboardEntry(ticker: str, name: str, rating: str, verdict: Verdict, score: int | None = None, trend: Trend | None = None, sentiment: str = "", earnings_outlook: str = "", risks: list[str] = [], catalysts: list[str] = [], latest: str = "", note: str | None = None)`
  - `ExtractedFields(score: int = Field(ge=0, le=100), trend: Trend, sentiment: str, earnings_outlook: str, risks: list[str] = Field(max_length=3), catalysts: list[str] = Field(max_length=3), latest: str)` — the extractor's structured-output schema, with `Field(description=...)` on each field.
  - `DashboardReport(session_date: date, generated_at: datetime, entries: list[DashboardEntry])`
  - `IndexQuote(name: str, close: float, pct_change: float)`
  - `MarketRecap(session_date: date, indices: list[IndexQuote], advancers: int, decliners: int, new_highs: int, new_lows: int, covered: int, total: int, leading: list[str], lagging: list[str])`
- Produces (in `watchlist.py`): `class WatchlistError(ValueError)`; `MAX_TICKERS = 15`; `load_watchlist(path: Path) -> list[str]`.

- [ ] **Step 1: Install the dependency**

Run: `pip install exchange_calendars` then add `"exchange_calendars>=X.Y"` (installed version) to `pyproject.toml` `dependencies`, alphabetically.
Expected: `python -c "import exchange_calendars as x; print(x.get_calendar('XNYS').name)"` prints `XNYS`.

- [ ] **Step 2: Write the failing tests** in `tests/daily/test_watchlist.py` (use `tmp_path`)

```python
def test_parses_comments_blanks_case_and_duplicates(tmp_path):
    p = tmp_path / "w.txt"; p.write_text("# mine\nnvda\n\n  AAPL  # core\nNVDA\n")
    assert load_watchlist(p) == ["NVDA", "AAPL"]

def test_bom_and_crlf_parse_like_clean_file(tmp_path):
    p = tmp_path / "w.txt"; p.write_bytes("﻿NVDA\r\nAAPL \r\n".encode("utf-8"))
    assert load_watchlist(p) == ["NVDA", "AAPL"]

def test_more_than_15_is_error(tmp_path):
    p = tmp_path / "w.txt"; p.write_text("\n".join(f"T{i}" for i in range(16)))
    with pytest.raises(WatchlistError, match="16"):
        load_watchlist(p)

def test_invalid_ticker_names_line(tmp_path):
    p = tmp_path / "w.txt"; p.write_text("NVDA\nbad ticker!\n")
    with pytest.raises(WatchlistError, match="line 2"):
        load_watchlist(p)

def test_empty_is_error(tmp_path):
    p = tmp_path / "w.txt"; p.write_text("# nothing\n")
    with pytest.raises(WatchlistError):
        load_watchlist(p)
```

- [ ] **Step 3: Run to verify they fail**

Run: `pytest tests/daily/test_watchlist.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 4: Implement `schemas.py` and `load_watchlist`**

Read with `encoding="utf-8-sig"`; strip inline `#` comments; validate each ticker with regex `^[A-Z0-9.\-^=]{1,15}$` after `normalize_symbol` from `tradingagents.dataflows.symbols`; error messages include the 1-based line number.

- [ ] **Step 5: Run to verify they pass**

Run: `pytest tests/daily/test_watchlist.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tradingagents/daily tests/daily
git commit -m "feat(daily): schemas, watchlist loader, exchange_calendars dependency"
```

---

### Task 2: Market clock

**Files:**
- Create: `tradingagents/daily/market_clock.py`, `tests/daily/test_market_clock.py`

**Interfaces:**
- Produces: `session_for(job: Literal["dashboard", "recap"], now_utc: datetime) -> date | None`; `SGT = ZoneInfo("Asia/Singapore")`; `NY = ZoneInfo("America/New_York")`.
- Rules (spec §3, §4):
  - dashboard: `ny_today = now_utc.astimezone(NY).date()`; if `ny_today` is not an XNYS session → `None`; else the previous XNYS session before `ny_today`.
  - recap: `ny_today = now_utc.astimezone(NY).date()` (06:00 SGT = 17:00/18:00 ET, same US day); if it is an XNYS session → `ny_today`, else `None`.

- [ ] **Step 1: Write the failing tests** (all `now_utc` are aware UTC datetimes)

```python
U = timezone.utc
def test_dashboard_normal_tuesday():           # 2026-10-06 11:00Z = Tue 19:00 SGT, 07:00 ET
    assert session_for("dashboard", datetime(2026,10,6,11,0,tzinfo=U)) == date(2026,10,5)
def test_dashboard_monday_reports_friday():
    assert session_for("dashboard", datetime(2026,10,5,11,0,tzinfo=U)) == date(2026,10,2)
def test_dashboard_skips_us_holiday():         # Thanksgiving 2026-11-26
    assert session_for("dashboard", datetime(2026,11,26,11,0,tzinfo=U)) is None
def test_dashboard_day_after_holiday_reports_day_before_holiday():
    assert session_for("dashboard", datetime(2026,11,27,11,0,tzinfo=U)) == date(2026,11,25)
def test_recap_normal():                       # 2026-10-06 22:00Z = Wed 06:00 SGT
    assert session_for("recap", datetime(2026,10,6,22,0,tzinfo=U)) == date(2026,10,6)
def test_recap_holiday_none():
    assert session_for("recap", datetime(2026,11,26,22,0,tzinfo=U)) is None
def test_recap_early_close_runs():             # 2026-11-27 early close
    assert session_for("recap", datetime(2026,11,27,22,0,tzinfo=U)) == date(2026,11,27)
def test_recap_winter_time():                  # EST: 2026-12-15 22:00Z = 17:00 ET
    assert session_for("recap", datetime(2026,12,15,22,0,tzinfo=U)) == date(2026,12,15)
```

- [ ] **Step 2: Run to verify they fail** — `pytest tests/daily/test_market_clock.py -v` → FAIL (`ImportError`).
- [ ] **Step 3: Implement `session_for`** using `exchange_calendars.get_calendar("XNYS")`, `is_session` and `date_to_session(..., direction="previous")` / `previous_session`. Raise `ValueError` if `now_utc` is naive.
- [ ] **Step 4: Run to verify they pass** — expected 8 passed; also run `TZ=America/New_York pytest tests/daily/test_market_clock.py` → 8 passed.
- [ ] **Step 5: Commit** — `git commit -m "feat(daily): NYSE session clock for dashboard and recap"`

---

### Task 3: Rendering

**Files:**
- Create: `tradingagents/daily/render.py`, `tests/daily/test_render.py`

**Interfaces:**
- Consumes: Task 1 schemas.
- Produces: `render_dashboard(report: DashboardReport) -> list[str]` (summary first, then one message per buy/watch/sell entry); `render_recap(recap: MarketRecap) -> str`; `render_failure(job: str, exc: BaseException) -> str` → `f"❌ {job.title()} run failed: {type(exc).__name__}: {exc}"`.

- [ ] **Step 1: Write the failing snapshot tests.** Expected strings are the spec §3/§4 layouts verbatim. Required cases:

```python
def test_dashboard_summary_counts_and_lines():
    # entries: NVDA watch Hold 62 bullish; AAPL sell Underweight 35 bearish; XYZ review note "Analysis failed: ValueError"
    msgs = render_dashboard(report)
    assert msgs[0].splitlines()[:2] == ["🎯 2026-10-05 Decision Dashboard",
                                        "2 stocks analyzed | 🟢 Buy: 0  🟡 Watch: 1  🔴 Sell: 1"]
    assert "🟡 NVIDIA Corporation (NVDA): Watch (Hold) | Score 62 | Bullish" in msgs[0]
    assert "⚠️ XYZ Inc (XYZ): Analysis failed: ValueError" in msgs[0]
    assert len(msgs) == 3          # summary + NVDA + AAPL; no message for review

def test_dashboard_stock_message_exact():   # full expected text for NVDA incl. "Generated: 19:00 SGT" from generated_at
def test_empty_lists_render_none_identified():
    assert "🚨 Risks:\n• None identified" in msgs[1]
def test_skipped_line():
    assert "⏭ Microsoft Corporation (MSFT): daily model quota reached" in msgs[0]
def test_trend_labels():  # bullish→Bullish, range_bound→Range-bound, bearish→Bearish
def test_recap_exact():   # full expected text; 🟢 for 0.00 change, 🔴 for -0.12
def test_recap_partial_coverage_heading():
    assert "📈 Market Breadth (S&P 500) (471/503)" in render_recap(recap_with(covered=471, total=503))
def test_recap_full_coverage_no_count():   # covered=480,total=503 (95.4%) → no "(480/503)"
def test_failure_message():
    assert render_failure("dashboard", ValueError("boom")) == "❌ Dashboard run failed: ValueError: boom"
```

`generated_at` is an aware UTC datetime; the footer converts to SGT `HH:MM`.

- [ ] **Step 2: Run to verify they fail** — `pytest tests/daily/test_render.py -v` → FAIL.
- [ ] **Step 3: Implement the three functions.** Percent format `f"{pct:+.2f}%"`, close `f"{close:.2f}"`. Count only buy/watch/sell in the header.
- [ ] **Step 4: Run to verify they pass** — all pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(daily): Telegram text rendering for dashboard and recap"`

---

### Task 4: Telegram sender

**Files:**
- Create: `tradingagents/daily/telegram.py`, `tests/daily/test_telegram.py`

**Interfaces:**
- Produces: `class TelegramError(RuntimeError)`; `split_message(text: str, limit: int = 4096) -> list[str]`; `send(texts: list[str], token: str, chat_id: str, *, session: requests.Session | None = None, sleep: Callable[[float], None] = time.sleep) -> None`.

- [ ] **Step 1: Write the failing tests** (mock `session.post`; inject a no-op `sleep`)

```python
def test_split_on_line_boundaries():
    text = "\n".join(["x" * 100] * 50)              # 5049 chars
    parts = split_message(text)
    assert all(len(p) <= 4096 for p in parts) and "\n".join(parts) == text
def test_single_overlong_line_hard_split():
    parts = split_message("y" * 9000)
    assert [len(p) for p in parts] == [4096, 4096, 808]
def test_send_posts_each_part_in_order():           # 2 texts → 2 POSTs to .../bot<token>/sendMessage with chat_id and text
def test_retry_after_429_honours_retry_after():
    # first response 429 {"parameters":{"retry_after":3}}, then 200 → sleep called with 3, 2 posts
def test_gives_up_after_5_attempts():
    # always 500 → raises TelegramError; sleep called 4 times
def test_token_not_in_error_message():
    # always 500 → str(exc) does not contain the token
```

- [ ] **Step 2: Run to verify they fail** — FAIL.
- [ ] **Step 3: Implement.** Endpoint `https://api.telegram.org/bot{token}/sendMessage`, JSON body `{"chat_id", "text", "disable_web_page_preview": True}`, timeout 30 s. Retry on 429 and 5xx up to 5 attempts; delay = `retry_after` when given, else `2 ** attempt`.
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(daily): Telegram sender with splitting and retries"`

---

### Task 5: Market recap data

**Files:**
- Create: `tradingagents/daily/recap.py`, `tradingagents/daily/data/sp500.txt`, `tests/daily/test_recap.py`
- Modify: `pyproject.toml` — add `"tradingagents.daily" = ["data/*.txt"]` under the existing `[tool.setuptools.package-data]` table; read the file with `importlib.resources.files("tradingagents.daily") / "data" / "sp500.txt"`.

**Interfaces:**
- Consumes: `MarketRecap`, `IndexQuote`.
- Produces:
  - `INDICES = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow"}`
  - `SECTORS = {"XLK": "Technology", "XLF": "Financials", "XLV": "Health Care", "XLE": "Energy", "XLI": "Industrials", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication Services"}`
  - `class RecapDataError(RuntimeError)`
  - `build_recap(session_date: date, download: Callable[..., pd.DataFrame] = yf.download) -> MarketRecap`
  - Pure helpers tested directly: `index_quotes(df, session_date) -> list[IndexQuote]`, `breadth(df, session_date) -> tuple[adv, dec, highs, lows, covered]`, `rank_sectors(df, session_date) -> tuple[list[str], list[str]]`.

`df` is the `yf.download(..., group_by="column", auto_adjust=False)` shape: MultiIndex columns `(field, ticker)` with fields `Close`, `High`, `Low`.

- [ ] **Step 1: Write `sp500.txt`** — current S&P 500 members, one Yahoo ticker per line (class shares with `-`, e.g. `BRK-B`). Expected: ~503 lines, no blanks.

- [ ] **Step 2: Write the failing tests** using small hand-built DataFrames:

```python
def test_index_quotes_pct_change():        # closes 100 → 101.5 → pct 1.5, close 101.5
def test_missing_index_raises():           # ^DJI column all NaN → RecapDataError
def test_breadth_counts_and_ties():        # A up, B down, C unchanged → adv 1, dec 1, covered 3
def test_breadth_nan_last_row_is_missing_not_unchanged():
    # D has NaN on session_date → covered excludes D; adv/dec unchanged
def test_52w_high_and_low():
    # 252 rows; E's session High ≥ max High of prior 251 → highs 1; F's session Low ≤ min Low prior 251 → lows 1
def test_rank_sectors_top3_bottom3():      # leading ordered best first, lagging ordered worst first
def test_session_date_missing_raises():    # df has no row for session_date → RecapDataError
def test_build_recap_uses_injected_download():  # fake download returns fixtures; total == number of sp500 tickers passed
```

- [ ] **Step 3: Run to verify they fail** — FAIL.
- [ ] **Step 4: Implement.** `build_recap` makes 3 `download` calls: indices + sectors with `period="5d"`, members with `period="1y"`; the row for `session_date` is the session; the previous row is the prior close. Lagging = bottom 3 ordered worst first.
- [ ] **Step 5: Run to verify they pass.**
- [ ] **Step 6: Commit** — `git commit -m "feat(daily): market recap from yfinance indices, breadth and sector ETFs"`

---

### Task 6: Dashboard post-processing

**Files:**
- Create: `tradingagents/daily/postprocess.py`, `tests/daily/test_postprocess.py`

**Interfaces:**
- Produces:
  - `verdict_for(rating: str) -> Verdict`
  - `SCORE_BANDS: dict[str, tuple[int, int]]` = `{"Buy": (80, 100), "Overweight": (65, 79), "Hold": (45, 64), "Underweight": (30, 44), "Sell": (0, 29)}`
  - `clamp_score(rating: str, score: int) -> int`
  - `grounded(items: list[str], source: str) -> list[str]`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("r,v", [("Buy","buy"),("Overweight","buy"),("Hold","watch"),
                                 ("Underweight","sell"),("Sell","sell"),("REVIEW","review")])
def test_verdict_for(r, v): assert verdict_for(r) == v
def test_clamp_inside_band_unchanged(): assert clamp_score("Hold", 50) == 50
def test_clamp_above_band(): assert clamp_score("Hold", 70) == 64
def test_clamp_below_band(): assert clamp_score("Buy", 40) == 80
def test_grounded_keeps_items_without_numbers():
    assert grounded(["Strong AI demand"], "") == ["Strong AI demand"]
def test_grounded_drops_absent_number():
    assert grounded(["Revenue up 407.52%"], "revenue grew 40%") == []
def test_grounded_accepts_format_variants():
    src = "Net outflow of $1,234.5M; margin fell -12.5%"
    assert grounded(["Outflow 1234.5M", "Margin down 12.5%"], src) == ["Outflow 1234.5M", "Margin down 12.5%"]
def test_grounded_unit_must_match():
    assert grounded(["Cash $3.6B"], "cash of $3.6M") == []
```

- [ ] **Step 2: Run to verify they fail** — FAIL.
- [ ] **Step 3: Implement.** Number token regex: `\$?-?\d[\d,]*(?:\.\d+)?\s?(?:%|[KMB]\b|million|billion|thousand)?` (case-insensitive). Normalise: drop `$`, `,`, leading `-`, whitespace; map `thousand→K`, `million→M`, `billion→B`; upper-case. An item is kept when every normalised token in it is in the set of normalised tokens of `source`.
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(daily): verdict mapping, score clamping and grounding check"`

---

### Task 7: Dashboard orchestration

**Files:**
- Create: `tradingagents/daily/dashboard.py`, `tests/daily/test_dashboard.py`

**Interfaces:**
- Consumes: `load_watchlist` is called by Task 8, not here. Task 6 helpers; `ExtractedFields`, `DashboardEntry`, `DashboardReport`; `TradingAgentsGraph(selected_analysts, config=..., callbacks=...)` and `.propagate(ticker, trade_date) -> (final_state, signal)`; `create_tier_client(config, "quick").get_llm()`; `bind_structured(llm, ExtractedFields, "DashboardExtractor")`, `invoke_structured(structured_llm, prompt, "DashboardExtractor") -> ExtractedFields | None`; `resolve_instrument_identity(ticker)["company_name"]` (fallback: ticker).
- Produces:
  - `lean_config(env: Mapping[str, str] = os.environ) -> dict` — `build_default_config()` plus `max_debate_rounds=1`, `max_risk_discuss_rounds=1`, `output_language="English"`, `llm_max_retries=int(env.get("DAILY_LLM_MAX_RETRIES", "6"))`.
  - `selected_analysts(env) -> tuple[str, ...]` — from `DAILY_ANALYSTS`, default `("market", "news", "fundamentals")`; unknown names raise `ValueError`.
  - `is_quota_error(exc: BaseException) -> bool` — true when `exc` or any `__cause__`/`__context__` has class name `RateLimitError` or an int `status_code == 429`.
  - `class CallCounter(BaseCallbackHandler)` with `count: int`, incremented in `on_llm_start` and `on_chat_model_start`.
  - `extract_prompt(final_state: dict, analysts: tuple[str, ...], budget: int = 6000) -> str` — rubric (score bands), "use only facts stated below", then `final_rating`, `final_trade_decision`, and each selected analyst's report (state keys `market_report`, `news_report`, `fundamentals_report`, `sentiment_report`), each truncated to `budget` chars.
  - `run_dashboard(tickers: list[str], session_date: date, now_utc: datetime, *, graph_factory=None, extractor=None, identity=resolve_instrument_identity) -> tuple[DashboardReport, int]` — returns the report and total LLM call count. `graph_factory()` returns an object with `.propagate`; `extractor(prompt) -> ExtractedFields | None`. Defaults build the real graph and quick-tier extractor.

- [ ] **Step 1: Write the failing tests** with a `FakeGraph` (scripted `(state, signal)` or exception per ticker) and a scripted fake extractor:

```python
def test_happy_path_entry_fields():           # Hold + score 70 → verdict watch, score 64 (clamped), name from identity
def test_review_signal_becomes_review_entry():  # signal "REVIEW" → verdict review, note startswith "No readable rating"
def test_bad_ticker_exception_is_review_and_run_continues():
    # NVDAA raises ValueError("No data") → review, note "Analysis failed: ValueError: No data"; next ticker analysed
def test_quota_error_skips_remaining():
    # 2nd ticker raises openai-like RateLimitError → 2nd and 3rd verdict skipped, note "daily model quota reached"
def test_extractor_retry_then_fallback():
    # extractor returns None twice → entry has verdict/rating, note = first two sentences of executive summary
    # taken from final_trade_decision; score/trend None; extractor called exactly 2 times
def test_ungrounded_risk_dropped():           # risk with "99.9%" not in reports → removed
def test_is_quota_error_walks_cause_chain():  # RuntimeError raised `from` RateLimitError → True
def test_selected_analysts_default_and_social():
    assert selected_analysts({}) == ("market", "news", "fundamentals")
    assert selected_analysts({"DAILY_ANALYSTS": "market,social"}) == ("market", "social")
def test_selected_analysts_unknown_raises():
def test_extract_prompt_truncates_reports():  # report of 10_000 chars → at most 6000 of it appears
```

For the fallback, "executive summary" is the text following an `Executive Summary` heading in `final_trade_decision` when present, else its opening; split sentences on `(?<=[.!?])\s+`.

- [ ] **Step 2: Run to verify they fail** — FAIL.
- [ ] **Step 3: Implement.** Tickers run sequentially; one `CallCounter` instance is shared across all graphs and the extractor; on a quota error stop calling the graph.
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(daily): dashboard orchestration over lean TradingAgents runs"`

---

### Task 8: Command-line entry point

**Files:**
- Create: `tradingagents/daily/__main__.py`, `tests/daily/test_main.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv: list[str] | None = None, *, now_utc: datetime | None = None, env: Mapping[str, str] = os.environ, deps: Deps | None = None) -> int`, where `Deps` is a dataclass of `send`, `run_dashboard`, `build_recap`, `session_for`, `load_watchlist` (defaults: the real functions), so tests inject fakes.
- CLI: `python -m tradingagents.daily {dashboard,recap} [--dry-run] [--date YYYY-MM-DD] [--watchlist PATH (default watchlist.txt)]`.
- Behaviour:
  - `--date` overrides `session_for`; otherwise `None` → print `"No US session to report; nothing sent."`, return 0.
  - `--dry-run` prints messages separated by a line of `=` × 40 and never needs Telegram env vars.
  - Without `--dry-run`, `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are required; missing → message to stderr, return 2.
  - Dashboard prints `LLM calls: {n}` to stdout (the rollout measurement reads this).
  - Any exception: if Telegram env vars exist, try to `send([render_failure(job, exc)])` (swallow errors from that send), re-raise.

- [ ] **Step 1: Write the failing tests**

```python
def test_no_session_sends_nothing(capsys):     # session_for → None; send not called; returns 0
def test_dry_run_prints_and_does_not_send(capsys):  # recap dry-run → stdout contains "Market Recap"; send not called
def test_date_override_skips_clock():          # --date 2026-10-05 → session_for not called; build_recap got date(2026,10,5)
def test_missing_telegram_env_returns_2():
def test_dashboard_prints_call_count(capsys):  # fake run_dashboard returns (report, 37) → "LLM calls: 37"
def test_crash_sends_failure_then_raises():    # build_recap raises RecapDataError("no ^DJI") → send got
                                               # ["❌ Recap run failed: RecapDataError: no ^DJI"]; exception propagates
def test_bad_watchlist_fails_before_llm():     # load_watchlist raises WatchlistError → run_dashboard never called
```

- [ ] **Step 2: Run to verify they fail** — FAIL.
- [ ] **Step 3: Implement** with `argparse`; `if __name__ == "__main__": sys.exit(main())`.
- [ ] **Step 4: Run to verify they pass**; then run the whole suite: `pytest -q` → all pass (existing tests included).
- [ ] **Step 5: Manual smoke test (network, no LLM):** `python -m tradingagents.daily recap --dry-run --date <last weekday>` → prints a recap with plausible index levels.
- [ ] **Step 6: Commit** — `git commit -m "feat(daily): python -m tradingagents.daily entry point"`

---

### Task 9: Workflow, watchlist file, docs

**Files:**
- Create: `.github/workflows/daily.yml`, `watchlist.txt`
- Modify: `README.md` (new section "Daily Telegram dashboard" after "CLI Usage")

**Interfaces:**
- Consumes: Task 8 CLI.

- [ ] **Step 1: Write `watchlist.txt`** — header comment explaining format and the 15 limit, then `NVDA`, `AAPL`, `MSFT` as placeholders for the user to replace.

- [ ] **Step 2: Write `.github/workflows/daily.yml`** with:
  - `on.schedule`: `- cron: "0 11 * * 1-5"` and `- cron: "0 22 * * 1-5"`; `on.workflow_dispatch.inputs`: `job` (choice `dashboard`/`recap`, required), `date` (string, optional), `dry_run` (boolean, default false).
  - `permissions: { contents: read, models: read }`.
  - Two jobs (spec §2), both `ubuntu-latest`:
    - `dashboard`: `if: github.event.schedule == '0 11 * * 1-5' || inputs.job == 'dashboard'`, `timeout-minutes: 120`.
    - `recap`: `if: github.event.schedule == '0 22 * * 1-5' || inputs.job == 'recap'`, `timeout-minutes: 20`.
  - Steps (both): checkout → setup-python 3.12 → `pip install .` → run `python -m tradingagents.daily <job>` with `--date`/`--dry-run` when given. Dashboard also wraps the run with `actions/cache/restore` (path `~/.tradingagents/memory`, key `ta-memory-${{ github.run_id }}`, restore-keys `ta-memory-`) before, and `actions/cache/save` (same path and key, `if: always()`) after.
  - Env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` from secrets; `TRADINGAGENTS_LLM_PROVIDER: openai_compatible`; `TRADINGAGENTS_LLM_BACKEND_URL: https://models.github.ai/inference`; `OPENAI_COMPATIBLE_API_KEY: ${{ secrets.GITHUB_TOKEN }}`; `TRADINGAGENTS_DEEP_THINK_LLM` and `TRADINGAGENTS_QUICK_THINK_LLM` from repo **variables** (`vars.`) so the user changes models without editing YAML; `DAILY_ANALYSTS: ${{ vars.DAILY_ANALYSTS || 'market,news,fundamentals' }}`.
  - Use the same action major versions as `.github/workflows/ci.yml`.

- [ ] **Step 3: Validate the YAML**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/daily.yml'))"` (install `pyyaml` locally if missing; do not add it to the project).
Expected: no error.

- [ ] **Step 4: Write the README section**: fork, create bot with @BotFather, get chat ID, add the 2 secrets and the 2 model variables, edit `watchlist.txt`, run via "Run workflow", the schedule in SGT, the 60-day inactivity note, and "not investment advice".

- [ ] **Step 5: Commit** — `git commit -m "feat(daily): scheduled GitHub Actions workflow, watchlist and docs"`

---

### Task 10: Measurement and rollout (on the user's fork — needs the user)

Not code. Each step needs the user's GitHub fork and Telegram bot; stop and ask the user before each step that pushes, creates secrets or sends messages.

- [ ] **Step 1:** User forks TradingAgents; add the fork as a remote and push `feature/daily-us-dashboard` (after the user confirms). Set the fork's default branch or merge to its `main` so the schedule runs.
- [ ] **Step 2:** User creates the bot and adds `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` secrets and `TRADINGAGENTS_QUICK_THINK_LLM` / `TRADINGAGENTS_DEEP_THINK_LLM` variables (candidate GitHub Models IDs, e.g. a small and a mid model from the GitHub Models catalog).
- [ ] **Step 3 (measure):** set `watchlist.txt` to one ticker; dispatch `dashboard` with `dry_run: true`. Read `LLM calls: N` from the log. Compare `N × 15` against the account's current daily caps per model tier. If it does not fit, stop and bring options to the user (fewer analysts, smaller watchlist, different models) before Step 5.
- [ ] **Step 4:** dispatch `recap` (not dry-run) → message arrives in Telegram.
- [ ] **Step 5:** restore the real watchlist; dispatch `dashboard` (not dry-run) → messages arrive; check one stock's figures against its sources.
- [ ] **Step 6:** leave the schedules enabled; confirm the next scheduled runs arrive at 19:00 and 06:00 SGT.
