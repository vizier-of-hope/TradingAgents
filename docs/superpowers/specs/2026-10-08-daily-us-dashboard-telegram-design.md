# Daily US Decision Dashboard and Market Recap via Telegram — Design

Date: 2026-10-08
Status: Approved in conversation; awaiting written-spec review

## 1. Goal

Deliver two English reports to Telegram every US trading day, modelled on the
A-share 决策仪表盘 / 大盘复盘 samples the user supplied, but for US stocks:

1. **Decision Dashboard** — per-stock verdict, 0–100 score, trend, sentiment,
   earnings outlook, risks, catalysts and latest news for a personal watchlist,
   produced by TradingAgents' multi-agent analysis.
2. **Market Recap** — major indices, S&P 500 breadth and sector leaders/laggards
   for the US session that just closed.

Success means: both messages arrive on schedule without manual action, the
dashboard covers the whole watchlist (or says plainly which stocks it could not
cover and why), and no figure in a message is invented by the model.

Reports are LLM-generated research signals for the user's own monitoring, not
investment advice.

### Decisions made with the user

| Topic | Decision |
|---|---|
| Base | Extend this TradingAgents repo (not a new project, not daily_stock_analysis) |
| Market | US stocks |
| Delivery | Telegram bot |
| Runner | GitHub Actions cron on the user's fork |
| Language | English |
| Verdict scale | 3 buckets (Buy / Watch / Sell), with the 5-tier rating in brackets |
| Watchlist size | 6–15 stocks; lean "daily" analysis depth |
| Schedule | Dashboard 19:00 SGT Mon–Fri; Recap 06:00 SGT Tue–Sat |
| LLM | GitHub Models via the `openai_compatible` provider, authenticated by `GITHUB_TOKEN` |
| Dashboard approach | Lean graph run per stock + one extractor call (no change to core agents/schemas) |

### Out of scope

- Non-US markets, intraday alerts, trade execution, portfolio tracking.
- Changing existing agents, `PortfolioDecision`, the memory log format, or the CLI.
- A web UI or any channel other than Telegram.

## 2. Architecture

New subpackage `tradingagents/daily/`. Each module has one job and is testable
on its own. Nothing outside this subpackage changes except the new workflow,
`pyproject.toml` (one dependency) and the checked-in data files.

| Module | Responsibility | Depends on |
|---|---|---|
| `watchlist.py` | Read `watchlist.txt` at repo root: one ticker per line, `#` comments and blank lines ignored, tickers upper-cased and validated with the repo's existing symbol rules, duplicates removed, at most 15 (extra lines are an error, not silently dropped). | `dataflows/symbols.py` |
| `schemas.py` | Pydantic models `DashboardEntry`, `DashboardReport`, `MarketRecap` (Section 3, 4). | pydantic |
| `dashboard.py` | For each ticker: build the lean config, run `TradingAgentsGraph.propagate`, call the extractor, apply verdict mapping, score clamping and grounding check; return a `DashboardReport`. | graph, LLM client factory |
| `recap.py` | Fetch indices, breadth and sector data from yfinance; return a `MarketRecap`. No LLM. | yfinance |
| `render.py` | Pure functions `render_dashboard(report) -> list[str]` and `render_recap(recap) -> str`. | schemas |
| `telegram.py` | `send(texts: list[str])` via Bot API `sendMessage`; split any text over 4096 characters on line boundaries; retry 429/5xx with backoff honouring `retry_after`. | `requests` |
| `market_clock.py` | `session_for(job, now_utc) -> date | None`: the US session date the job should report on, or `None` when the job should not send (rules per job in Sections 3 and 4). | `exchange_calendars` |
| `__main__.py` | `python -m tradingagents.daily {dashboard,recap} [--dry-run] [--date YYYY-MM-DD]`. `--dry-run` prints messages to stdout instead of sending. `--date` overrides the session date for manual reruns. | all above |

Data files at repo root:

- `watchlist.txt` — the user's tickers, editable from GitHub's web UI.
- `tradingagents/daily/data/sp500.txt` — S&P 500 member tickers, refreshed by hand occasionally.

New dependency: `exchange_calendars` (NYSE holidays and early closes).

### Workflow `.github/workflows/daily.yml`

- Two jobs, `dashboard` and `recap`, each on its own cron (UTC; SGT is UTC+8 with no DST):
  - Dashboard: `0 11 * * 1-5` → 19:00 SGT Mon–Fri.
  - Recap: `0 22 * * 1-5` → 06:00 SGT Tue–Sat.
- `workflow_dispatch` with inputs `job` and optional `date`, for manual runs.
- `permissions: { contents: read, models: read }`.
- Dashboard `timeout-minutes: 120`; recap `timeout-minutes: 20`.
- Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- LLM configuration via env vars (no code change to switch provider later):
  - `TRADINGAGENTS_LLM_PROVIDER=openai_compatible`
  - `TRADINGAGENTS_LLM_BACKEND_URL=<GitHub Models inference endpoint>`
  - `OPENAI_COMPATIBLE_API_KEY=${{ secrets.GITHUB_TOKEN }}`
  - `TRADINGAGENTS_DEEP_THINK_LLM`, `TRADINGAGENTS_QUICK_THINK_LLM` — model IDs chosen after the measurement step (Section 7).
  - `DAILY_ANALYSTS` (default `market,news,fundamentals`).
- The memory log directory (`~/.tradingagents/memory/`) is restored and saved with
  `actions/cache` using key `ta-memory-${{ github.run_id }}` and restore-key
  prefix `ta-memory-`, so each run starts from the latest saved copy.

Prerequisite: the user forks TradingAgents to their own GitHub account and
pushes this branch there; Actions, secrets and `watchlist.txt` live on the fork.

## 3. Decision Dashboard

### Flow (19:00 SGT)

1. `market_clock.session_for("dashboard", now)` checks the upcoming session:
   today's date in New York (19:00 SGT is 06:00–07:00 ET the same day). If it
   is not a NYSE trading day, exit 0 without sending. Otherwise it returns the
   most recent completed session before it, which becomes the analysis
   `trade_date` and the date in the message heading.
2. Load the watchlist.
3. For each ticker, sequentially (rate caps make parallelism counterproductive):
   1. **Lean graph run** — `TradingAgentsGraph(config=lean_config)` and
      `propagate(ticker, trade_date)` with:
      - selected analysts from `DAILY_ANALYSTS` (default `market, news, fundamentals`; `sentiment` opt-in);
      - `max_debate_rounds = 1`, `max_risk_discuss_rounds = 1`;
      - `llm_max_retries` raised (value set after measurement) so 429s back off instead of failing;
      - `output_language = "English"`.
   2. **Extractor** — one structured-output call on the quick-think model.
      Input: `final_rating`, `final_trade_decision`, and the selected analysts'
      reports (each truncated to a fixed character budget). Output: the
      LLM-filled fields of `DashboardEntry`. The prompt instructs it to use only
      facts stated in the inputs.
   3. **Post-processing in code** (below).
4. Render and send: one summary message, then one message per stock.

### `DashboardEntry`

| Field | Type | Filled by |
|---|---|---|
| `ticker` | str | code |
| `name` | str | code (instrument identity already resolved by the graph) |
| `rating` | 5-tier str or `REVIEW` | code: `final_rating` as-is |
| `verdict` | `buy` / `watch` / `sell` / `review` / `skipped` | code: Buy, Overweight → buy; Hold → watch; Underweight, Sell → sell; REVIEW → review |
| `score` | int 0–100 | extractor, then clamped by code |
| `trend` | `bullish` / `range_bound` / `bearish` | extractor (from the market report) |
| `sentiment` | str, ≤ 2 sentences | extractor |
| `earnings_outlook` | str, ≤ 2 sentences | extractor (from the fundamentals report) |
| `risks` | list[str], ≤ 3 | extractor, then grounding check |
| `catalysts` | list[str], ≤ 3 | extractor, then grounding check |
| `latest` | str, ≤ 2 sentences | extractor (from the news report) |
| `note` | str or None | code: reason text for review / skipped / fallback entries |

### Post-processing rules

- **Score bands** (rubric given to the extractor, enforced by clamping):
  Buy 80–100, Overweight 65–79, Hold 45–64, Underweight 30–44, Sell 0–29.
  A score outside its rating's band is clamped to the nearest band edge, so
  score and verdict can never contradict each other.
- **Grounding check**: extract every numeric token (with optional `$`, `%`,
  `M`/`B`/`K` suffix and thousands separators) from each risk and catalyst.
  Normalise it (strip `$`, commas; keep the number and unit) and look for the
  same normalised number in the normalised source text. An item with any
  number not found is dropped. Items without numbers are kept.
- **Extractor validation failure**: retry once; on second failure build a
  fallback entry with `verdict`, `rating`, and `note` = the first two sentences of
  the decision's `executive_summary`, and empty optional fields.

### Message layout

Summary message:

```
🎯 {session_date} Decision Dashboard
{n_analyzed} stocks analyzed | 🟢 Buy: {b}  🟡 Watch: {w}  🔴 Sell: {s}

📊 Summary
{emoji} {name} ({ticker}): {Verdict} ({rating}) | Score {score} | {Trend}
...
```

Per-stock message:

```
{emoji} {name} ({ticker})
📰 Key Info
💭 Sentiment: {sentiment}
📊 Earnings outlook: {earnings_outlook}

🚨 Risks:
• {risk}
✨ Catalysts:
• {catalyst}
📢 Latest: {latest}

---
Generated: {HH:MM} SGT
```

- Emoji: 🟢 buy, 🟡 watch, 🔴 sell, ⚠️ review, ⏭ skipped.
- Review and skipped stocks appear in the summary as `{emoji} {name} ({ticker}): {note}`
  and get no per-stock message. They are not counted in Buy/Watch/Sell.
- Empty risk or catalyst lists render as `• None identified`.
- Plain text (no Telegram parse mode), so model text cannot break formatting.

## 4. Market Recap

### Flow (06:00 SGT)

1. `market_clock.session_for("recap", now)` returns the US session that ended
   in the last 24 hours, or `None` if that day was not a trading day (exit 0,
   no message). Early-close days run normally.
2. Three batched yfinance downloads:
   - **Indices** `^GSPC` (S&P 500), `^IXIC` (Nasdaq Composite), `^DJI` (Dow):
     session close and % change from the prior close.
   - **Breadth** — members in `sp500.txt`, one year of daily data:
     advancers / decliners (close vs prior close; unchanged counted in neither),
     new 52-week highs / lows (session high ≥ max high of the prior 251 sessions;
     session low ≤ min low likewise).
   - **Sectors** — XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLB, XLRE, XLC with
     display names; rank by % change; top 3 lead, bottom 3 lag.
3. Render and send one message.

### Message layout

```
🎯 {session_date} Market Recap

📊 Major Indices
- S&P 500: {close} ({🟢|🔴}{+/-pct}%)
- Nasdaq: {close} ({🟢|🔴}{+/-pct}%)
- Dow: {close} ({🟢|🔴}{+/-pct}%)

📈 Market Breadth (S&P 500)
Up: {adv} | Down: {dec} | 52w Highs: {hi} | 52w Lows: {lo}

🔥 Sectors
Leading: {s1}, {s2}, {s3}
Lagging: {s9}, {s10}, {s11}
```

- The date is the US session date, not the SGT date.
- 🟢 for change ≥ 0, 🔴 for change < 0; percentages to 2 decimals, closes to 2 decimals.
- If fewer than 95% of members return data, append `({covered}/{total})` to the breadth heading.
- If any index is missing, the job fails (no message with zeros).

## 5. Error Handling

| Failure | Behaviour |
|---|---|
| One ticker's graph run raises, or returns `REVIEW` | Entry with verdict `review`, `note` = short reason; continue with the next ticker. |
| Model quota exhausted (429 persists after retries) | Stop analysing; remaining tickers get verdict `skipped`, note `daily model quota reached`; still send. |
| Extractor output invalid twice | Fallback entry (Section 3). |
| Telegram send fails after retries | Job fails (GitHub notifies the repo owner). |
| Unhandled exception in a job | Best effort: send `❌ {Dashboard|Recap} run failed: {error type}: {message}` to Telegram, then exit non-zero. |
| Dashboard exceeds 120 min | Actions cancels it; nothing partial is sent. |
| Memory cache missing or evicted | Run continues with an empty memory log. |
| Invalid `watchlist.txt` | Job fails before any LLM call; Telegram failure message names the bad line. |

## 6. Testing

All tests live in `tests/` and run under the existing CI without network or LLM access.

- `render`: exact-text snapshot tests for dashboard (normal, review, skipped,
  fallback, empty lists) and recap (normal, partial coverage).
- `market_clock`: weekends, NYSE holidays, early closes, the SGT→US date shift for both jobs, `--date` override.
- `dashboard` post-processing: verdict mapping, score clamping per band, grounding check (kept, dropped, unit/format variants).
- `dashboard` orchestration: fake graph and fake extractor; per-ticker failure, quota exhaustion → skipped, extractor fallback.
- `recap`: fixture DataFrames for indices, breadth (incl. ties and missing members), 52-week highs/lows, sector ranking.
- `watchlist`: comments, blanks, duplicates, invalid tickers, more than 15.
- `telegram`: 4096-char splitting on line boundaries; 429 with `retry_after`; HTTP mocked.
- Manual: `--dry-run` locally and `workflow_dispatch` on the fork.

## 7. Rollout

1. **Measure** — on the fork, one `workflow_dispatch` dry run of the dashboard
   for one ticker on GitHub Models; log the number of LLM requests per model.
   Choose model IDs and `llm_max_retries` from the result. If the daily caps
   cannot fit 6–15 stocks, stop and bring options to the user before step 3.
2. **Recap** end to end (no LLM).
3. **Dashboard** end to end.
4. Enable both crons.

## 8. Open Risks

- GitHub Models daily request caps for high-tier models may be too low for a
  15-stock watchlist even at lean depth; mitigated by measurement first and
  provider configuration via env vars.
- GitHub cron can start late; the dashboard has ≥ 2.5 h of slack before the open.
- yfinance is unofficial and can break or rate-limit; the recap fails loudly
  rather than sending wrong numbers.
- GitHub disables scheduled workflows on forks after 60 days without repository
  activity; a manual dispatch or any commit re-enables them.
