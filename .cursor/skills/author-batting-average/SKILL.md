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

- Pull the archive. Substack: `python3 bat/arch.py subdomain` (`/api/v1/archive`). Blogs: the public archive or sitemap. Seeking Alpha: the public author API only.

```bash
python3 bat/sa_one.py "Author Name" author-slug
```

  Title, date, ticker, and sentiment are enough for Seeking Alpha. Do not fetch full SA bodies for past pitches. If the API returns a bot check (HTTP 401, 403, or 429), stop. Do not retry with cookies and do not bypass anything.
- Include deleted or moved posts when you can find them (for example the Wayback Machine) so survivorship bias stays limited.
- Keep single-stock LONG pitches only (a buy or a long thesis, including updates). Drop recaps, macro, holds, sells, and shorts.
- Count each ticker once per window. Use the author's first pitch on that ticker inside the window.

`python3 bat/pitches.py` turns Substack pitch lists plus `bat/sa_auth.json` into `bat/pitches.json`. Extend the pitch list with what you actually found. Do not invent pitches.

## 2. Windows (relative to today)

- **1-year:** published 1–2 years ago. Measure the 12-month total return from the publish-date close.
- **2-year:** published 2–3 years ago. Measure the 24-month total return from the publish-date close.

`bat/calc.py` sets both windows from today's date.

## 3. Returns and benchmark

- Total return (adjusted close, dividends included) from the publish date to the publish date plus 12 or 24 months.
- Benchmark over those same dates: SPY for US-listed stocks, XIC.TO for Canadian-listed stocks (`.TO` and `.V`), unless the caller sets another benchmark.
- Delisted or acquired stocks: use the buyout price or the last trade. If the outcome cannot be found, exclude the pitch and note why. Known buyouts live in the `BUY` map in `bat/calc.py`; add a real deal, never a guessed price.

## 4. Score

- A pitch scores 1 when it beat its benchmark and 0 otherwise.
- Batting average = hits / pitches evaluated. Always show hits/total and the percent (for example `7/10 = 70%`).
- Also report the median excess return versus the benchmark, plus the best and worst pick.
- No pitches in a window: `n/a`. Flag a sample under 5 as small. Those authors do not rank in the top-5 tables.

The report column **BA 2y (1y)** prefers the 2-year average (`hits/n = %`). If there is no 2-year sample, use the 1-year average tagged `(1y)`. If neither exists, `n/a`.

## 5. Output

```bash
python3 bat/pitches.py
python3 bat/calc.py
```

`bat/calc.py` writes `state/batting.json`. Each pitch stores ticker, date, URL, title, stock return, benchmark return, and hit. The report reads this file. Authors with no usable archive get a `note` such as `archive starts YYYY-MM-DD` and null summaries.
