---
name: author-batting-average
description: >-
  Calculate a stock-pitch author's batting average: the share of past long
  pitches that beat the benchmark over 1-year and 2-year windows. Use on its
  own when the user asks for an author's track record or batting average, and
  as part of the stock screen for every author on the ranked list.
---

# Author batting average

Measures how often an author's past long pitches beat the market. The result is reported. It is not part of the /6 score unless the caller says otherwise.

## 1. Collect the author's past pitches

Substack pitches are detected from the archive. A title that happens to omit the ticker is still a pitch when the body names one company.

```bash
python3 bat/pitches.py subdomain
python3 bat/pitches.py sylencecapital p14capital --limit 20
```

`bat/lib.py` keeps a post only when it is a single US or Canada long. One pitch per ticker per window: the author's first pitch on that ticker inside the window.

- **Title.** If the title (and subtitle) name exactly one ticker, the method is `title`. A dual listing such as `(TSXV: SUM or OTC: SUMMF)` is one company; the listed line is the ticker.
- **Body.** If the title has no ticker, or names more than one company, fetch the public post at `https://<host>/api/v1/posts/<slug>`. Responses are cached under `cache/` (gitignored). Uncached calls wait `--sleep` seconds (default 1). The method is `body`. The 2-year batting-average pass fetches the body even when the title already names the ticker, so a hold or short in the body is visible. Each network call has a hard wall-clock cap. Body fetches overlap. One author has about a 300 second budget; a partial result past that budget is not saved.
- The primary ticker is the one in the opening text, or the one repeated most often: `$TICKER`, `(NYSE: X)`, `(NASDAQ: X)`, `(TSX: X)`, `(TSXV: X)`, `ticker: X`. If the body never names a ticker, look the company name up on Yahoo and keep a US or Canada equity. ETFs and other listings are dropped.
- **Long stance for the /6 score.** Explicit disclosure ("I own", "I am long", "my position", "I bought") or buy/thesis language ("investment thesis", "LONG $TICKER", "why I own", "quick pitch"). "May hold" does not count. Drop bearish, hold, recap, macro, watchlist, screen, and closed-position notes.
- **2-year batting average.** `bat/longcheck.py` is looser. `exclude_reason` drops a short, a sell rating, or a hold rating unless `is_long` is `long` (clear ownership: I own, I am long, my position, I hold shares). A hold with that ownership stays in. No such signal means the pitch still counts. Recap, macro, watchlist, foreign listings, and closed exits are still not pitches. Exclusions are counted by reason in `ba2y_excl`.
- Each kept pitch stores `method` (`title` or `body`) and `confidence` from 0 to 1. A paywalled preview is not mined for a ticker. Do not bypass a paywall.

`pitches_title` and `pitches_body` in `state/source_stats.csv` count those 2-year-window pitches by method. Until detection, both stay blank. `python3 scripts/source_upkeep.py --plan` rewrites the stats file and does not change the source list. It does not recompute a stored batting average unless that author is up for removal or is an add candidate. `ba_updated` is the calculation date. There is no expiry. `--full-ba` runs the resumable pass.

Seeking Alpha is separate. Title, date, ticker, and sentiment are enough. Do not fetch full SA bodies for past pitches.

```bash
python3 bat/sa_one.py "Author Name" author-slug
```

If the API returns a bot check (HTTP 401, 403, or 429), stop. Do not retry with cookies and do not bypass anything.

Blogs: use the public archive or sitemap and the same long-pitch rules. Include deleted or moved posts when you can find them (for example the Wayback Machine) so survivorship bias stays limited.

`python3 bat/pitches.py` with no subdomain writes `bat/pitches.json` from the hand list plus `bat/sa_auth.json`. Passing a subdomain detects that author and replaces their hand-entered rows. Do not invent pitches.

## 2. Windows (relative to today)

- **1-year:** published 1–2 years ago. Measure the 12-month total return from the publish-date close.
- **2-year:** published 2–3 years ago. Measure the 24-month total return from the publish-date close.

`bat/calc.py` sets both windows from today's date.

## 3. Returns and benchmark

- Total return (adjusted close, dividends included) from the publish date to the publish date plus 12 or 24 months.
- Benchmark over those same dates: SPY for US-listed stocks, XIC.TO for `.TO` and `.V` only, unless the caller sets another benchmark. `.CN` and `.NE` use SPY on this path.
- If a ticker has no price data, retry `SYM.TO`, then `SYM.V`. Retry a Yahoo timeout. Never cache a timeout as no data, and do not count a timeout as delisted (`ba2y_lost_px`). Only a real Not Found is cached, for 7 days (`ba2y_lost_notfound`). Those lost pitches are not part of n.
- Delisted or acquired stocks: use the buyout price or the last trade. If the outcome cannot be found, exclude the pitch and note why. Known buyouts live in the `BUY` map in `bat/calc.py`; add a real deal, never a guessed price.

## 4. Score

- A pitch scores 1 when it beat its benchmark and 0 otherwise.
- Batting average = hits / pitches evaluated. Always show hits/total and the percent (for example `7/10 = 70%`).
- Also store `ba2y_p_lt_hits`: the binomial chance of fewer hits than this, `P(X <= hits-1)` with n pitches and p=0.5. It is 0 when hits is 0, and blank when n is missing. Show it on every source-upkeep proposal and in the report. Sort batting summaries by it, highest first.
- Also report the median excess return versus the benchmark, plus the best and worst pick.
- No pitches in a window: `n/a`. Flag a sample under 5 as small. Those authors do not rank in the top-5 tables.
- Source upkeep drops an author when this 2-year average is 33% or less on at least 5 pitches.

The report column **BA 2y (1y)** prefers the 2-year average (`hits/n = %`, with `p_lt`). If there is no 2-year sample, use the 1-year average tagged `(1y)`. If neither exists, `n/a`. The column does not change the /6 score.

An author who has been dropped is listed in `config/sources_dropped_never_readd.csv` and is not added back. Do not reactivate that author from the dormant list.

## 5. Output

```bash
python3 bat/pitches.py
python3 bat/calc.py
```

`bat/calc.py` writes `state/batting.json`. Each pitch stores ticker, date, URL, title, stock return, benchmark return, and hit. The report reads this file. Authors with no usable archive get a `note` such as `archive starts YYYY-MM-DD` and null summaries.
