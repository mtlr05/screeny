---
name: stock-screen
description: >-
  Run the on-demand Screeny stock screen: sweep sources, triage write-ups,
  read them in full, score them out of 6, and write the ranked report.
  Use when the user says "run the stock screen", "screen this week's articles",
  "screen articles since", or asks for a weekly or full pass over Substack,
  blog, Seeking Alpha, or Value Investors Club stock pitches.
---

# Stock screen

On-demand only. "This week" means the last 7 days. A full run means the last 4 months. Do not invent a schedule.

Standing rules in `AGENTS.md` win if this file and the chat disagree. Do not change the screening rules or the /6 rubric below.

Run commands from the repo root.

## 1. Sweep sources

```bash
python3 scripts/weekly_sweep.py
python3 scripts/weekly_sweep.py --since YYYY-MM-DD
```

The script pulls every active Substack archive in `config/sources.csv`, skips URLs already in `state/seen_posts.csv`, appends new URLs, and writes `reports/triage_<date>.json`, `reports/stats_<date>.json`, and `reports/substack_screen_<date>.csv`.

A free post is dropped on the title only when the title or subtitle is a recap, a macro note, or a list. Those words match as whole words, so a company name is not dropped for a fragment such as "chart" inside "charter". A missing pitch keyword in the title is not a drop.

Every other free post is fetched (the first 1,500 words). Drop it only when that text is clearly not a single-stock pitch (a macro piece, a book review, a general essay, a multi-stock list, or no identifiable listed company) or the author is short, selling, or on hold. An unclear post stays a candidate. A post already in `state/seen_posts.csv` is not fetched again.

Every post in the window is a row in the screen file (`url`, `title`, `decision`, `reason`), including paywalled posts and title drops. Drop counts in `reports/stats_<date>.json` are read back from that file. When `state/scored.json` includes `substack_screen` set to that path, the report uses the same file for those counts.

Paywalled (`audience` other than everyone) posts are dropped here and are not scored. The title pass is not the full screening rule. Listing, size, and the long disclosure are still decided after the full read.

Manual sources in `config/sources.csv` (MicroCapClub, r/SecurityAnalysis, r/CanadianInvestor, r/Microcap, Value Investors Club, Seeking Alpha, blogs) are not pulled by the Substack sweep. Check them in this same run:

```bash
python3 scripts/rss.py FEED_URL --since YYYY-MM-DD
```

If a feed returns 403, 429, or no entries, record it as unreachable and move on. Add write-up URLs to the triage list.

Source adds and drops are the last step of the run (section 11). Do not add or remove a source during the sweep.

## 2. Earnings-drop overreactions

```bash
python3 scripts/earnings_drops.py
```

Optional universe file: `config/universe.csv` with a `ticker` column. The script also reads tickers in `state/returns.json` and `state/articles_scored.csv`. It lists small/mid-cap US and Canada names with a one-day drop of 10% or more in the past week.

For each name: confirm the drop was earnings-day news, confirm listing and size, then search the last 7 days for a thesis post. Add those URLs to the triage list. Do not score the drop itself.

## 3. Value Investors Club

Each run, check VIC public ideas that have newly come off the ~45-day embargo (published about 45–52 days ago, so they show up in the last-7-days public window). Screen and score them with the same rules as every other source. If the write-up does not disclose a long position, drop it as `author not long`.

## 4. Seeking Alpha

Seeking Alpha is one pull for this run. It is not a tracked source and it is not a row in `state/source_stats.csv` or `state/seen_posts.csv`. Never open investing groups, marketplace, or Alpha Picks. Do not paste, request, or store a password, a token, or a cookie.

Use the machine's signed-in browser. Open https://seekingalpha.com and check that the account menu is visible and an article page shows full text. If the session has expired, stop and ask the user to sign in, then check again. Do not log in yourself. Free-in-full articles only.

Past pitches, for batting average only, stay on the public author API: `python3 bat/sa_one.py "Author Name" author-slug`. Title, date, ticker, and sentiment are enough.

New articles this run, after the Substack sweep and before the full-text triage:

1. Page the Long Ideas list for the window. Also page an author or ticker feed when one is in scope. For each row save title, author, the date text, the primary ticker, and the URL. Convert dates to YYYY-MM-DD (`Today`, `Yesterday`, and `Fri, Oct 9` all become a real date). Skip `/symbol/`, `/author/`, marketplace, and `/alpha-picks/` URLs. Stop at the first row older than the window, or after three scrolls with nothing new. Write `reports/sa_list_<date>.csv` with columns `url,article_id,source,author,date,title,ticker,date_text`. `source` is `SA Long Ideas`, `SA author feed`, or `SA ticker feed`.
2. Cheap screen. No body yet. The script applies the same recap, multi-stock, and fund patterns as the reference screen, then asks Yahoo for quote type, exchange, and market cap. It keeps a single US or Canada equity under US$10B at publish.

```bash
python3 scripts/sa_ingest.py screen reports/sa_list_<date>.csv
```

That writes `reports/sa_candidates_<date>.csv` and `reports/sa_read_order_<date>.csv`. Columns extend `seen_posts` with `author,ticker,mcap_usd,exchange,sa_status,drop_reason`. `source` is `Seeking Alpha`. A kept row has `sa_status` `screened`. Read in the order file: tickers not yet scored first, then the rest by date, so a rate limit cuts off the least useful reads.
3. Full read, in that order, 20–30 seconds apart. Prefer the rendered page text. Do not use a PDF unless the page will not copy; the checker unwraps wrapped lines before it counts words. Open the article, scroll to the disclosure, and save `fulltext/sa_<id>.txt` with `URL`, `TITLE`, `AUTHOR`, `DATE`, `TICKERS`, a `=== SUMMARY ===` section, `=== ARTICLE BODY ===`, and `=== ANALYST'S DISCLOSURE ===`. If the first save is under 600 words, reload once, scroll to "Analyst's Disclosure", and save again before treating it as a preview.
4. Classify each saved file:

```bash
python3 scripts/sa_ingest.py check fulltext/sa_<id>.txt
```

`full` means the body is at least 600 words, there is no paywall marker, and the disclosure says a beneficial long position in the shares of that ticker. A short body, a paywall marker (`Subscribe to continue`, `To continue reading`, `only available to Premium`, `Sign up to continue`), or a missing disclosure is `preview` and is not scored. A disclosure that does not name the ticker is `not_long`.
5. If the page is a Press & Hold bot check, a captcha, or HTTP 403 or 429, pause and try that article once more. If it fails again, stop. `check` exits 3 on a bot-check page. The unread remainder stays in `reports/sa_read_order_<date>.csv`. Next time the user is signed in, continue with:

```bash
python3 scripts/sa_ingest.py resume reports/sa_read_order_<date>.csv
```

Score only what was already read in full.
6. Merge the articles that passed into the triage list. Dedupe is `state/sa_results.json` (skip ids already recorded). Do not add these URLs to `state/seen_posts.csv`.

```bash
python3 scripts/sa_ingest.py merge reports/sa_candidates_<date>.csv reports/triage_<date>.json
```

That writes `state/sa_breakdown.json` (`li`, `li_from`, `li_to`, `kept`, `read`, `previews`, `skipped_unread`, `passed`, `scored`) for the report appendix. Section 7 screening and section 8 scoring then apply as they do for any other article. After scoring, set `scored` to the number actually scored.

```bash
python3 scripts/sa_ingest.py self-test
```

That runs the screen, the preview and long-disclosure checks, the bot-check stop, and dedupe on fake rows. It does not touch the network.

## 5. X

Do not use the X MCP. Do not read or rebuild an account list. X links are optional. The sweep does not pull X-linked blogs. If the user pastes write-up links, add those URLs to the triage list and read them under the same rules. The original run's two `x_network_blog` posts are not part of this repo's sourced count unless those links are pasted.

## 6. Triage, then read in full

Hand-triage titles before fetching: drop non-US/Canada listings, caps above about US$10B, holds, and recaps. Do **not** drop follow-up updates, earnings reviews, or revisits. They are pitches and are scored like any other article.

Fetch Substack text (no jq):

```bash
python3 scripts/grab_fulltext.py reports/triage_YYYY-MM-DD.json
```

A paywall, a truncated body, or a preview means drop. Saved files land in `fulltext/` (gitignored).

`python3 scripts/triage2.py` can order the reading queue from saved text. Its number is not the /6 score.

## 7. Screening (all must hold)

Apply this before a name can be scored:

- Published inside the window (7 days, or 4 months on a full run).
- Readable in full. Any length qualifies. No word-count cutoff, except the Seeking Alpha check that a short page is a preview and must be dropped.
- A single-stock bullish pitch, including updates and earnings reviews. Drop recaps, macro, holds, and "still researching".
- Small/mid cap, under about US$10B.
- Listed in the US or Canada.
- Not already scored.
- Has a moat or an edge (graded later; screening only requires that one exists).
- The author discloses a long position. Drop reason `author not long` otherwise.

Record an ambiguous disclosure (the "may hold" kind of line) and drop it. Prioritise posts with a price target, a valuation section, and a management discussion.

## 8. Score out of 6

One point each. Partial credit is as stated. Small/mid cap and US/Canada listing are filters, not scored.

1. Thesis with a secular runway or growth driver. Cheap but no growth (asset value, cash pile, wind-down, low multiple only) = 0.5.
2. Return ~40%/yr from the publish-day close using the author's target and timeframe (default 2 years). Compute it with `scripts/px.py` and print the formula (target, publish close, horizon) in the one-pager `notes.return_formula`. 25–40%/yr = 0.5. Below 25%/yr = 0.
3. CEO is a large shareholder. Judge this only from the article or a cited filing. Roughly 5%+ = 1; 1–5% = 0.5. If neither source states the stake, score 0 and write "not stated". Do not use unstated knowledge.
4. Moat or edge (best of the two). Moat is judged on the business model against the five types (intangibles, switching costs, network effects, cost advantage, efficient scale), with mechanism, trend, and main threat: Strong 1 / Moderate 0.75 / Narrow 0.5. Edge = a proven operator, capital allocator, or dealmaker with evidence, or an obsessive founder-builder (built from scratch, product-led, evidence-backed). A good guidance record supports an edge.
5. Differential view, written by you: the specific reason the market is wrong (stigma or category label, a temporary or mundane issue, neglect) and why it should correct, compared with what the price implies and with other coverage. Score 1 only when the article states both the cause of the mispricing and why it corrects. Otherwise 0.5. Matches consensus = 0. An overreaction to temporary news supports it.
6. Dated catalyst: 1 only for a named event with a date inside 24 months. Named but undated = 0.5. None = 0.

Check the publish-day close:

```bash
python3 scripts/px.py YYYY-MM-DD TICKER
```

Benchmark for "since publish" in the report is IWM for US listings and XIC.TO for Canada (`.TO`, `.V`, `.CN`).

### Reported, not scored

These do not change the /6 score. Put them on the one-pager and in per-name notes:

- Fact-checks of prices, targets, figures, and history against filings and market data. Flag errors and stale prices. Restate upside from the publish-day close.
- Author batting average (the author-batting-average skill).
- Guidance track record: management guidance over the last 4–8 quarters, met / beat / missed.
- Balance-sheet red flags: cash runway under 24 months, dilution, heavy debt, SBC above about 10% of revenue.
- Strategic or expert holders.
- Overreaction context: a drop of about 10–15% or more on news that does not change the thesis.

## 9. Batting averages

For every author on the top list and the next six, follow `.cursor/skills/author-batting-average/SKILL.md`. Save `state/batting.json`. Minimum 5 pitches to appear in the top-5 tables.

Substack detection for the /6 score is `python3 bat/pitches.py subdomain`. A title that names one US or Canada ticker is method `title`. When the title has no ticker, or more than one company, the script fetches the public post body (`/api/v1/posts/<slug>`, cached). Uncached calls wait `--sleep` seconds (default 1). Each pitch is tagged `title` or `body` with a confidence. The upkeep batting-average pass fetches bodies for the 1–3 year window in parallel, including posts whose title already names a ticker. The next source-upkeep `--plan` writes the 2-year counts to `pitches_title` and `pitches_body` in `state/source_stats.csv`.

The /6 score still requires an explicit long. The 2-year batting average is one pitch per ticker, published 2–3 years ago. `bat/longcheck.py` drops a short, a sell, and a hold unless the body shows ownership. An unclear stance with no such signal still counts. A bare symbol with no listing is retried as `.TO`, then `.V`. The benchmark is XIC.TO for `.TO` and `.V`, and SPY otherwise. `ba_updated` is the calculation date and `ba_method` is `v2-excl-TO`. A stored average has no expiry and is recalculated only for an add candidate or a removal proposal.

`p_lt_hits_by_chance` is binomial `P(X <= hits-1)` with p=0.5. It is stored as `ba2y_p_lt_hits`, shown in the report, and summaries sort by it, highest first. Median stock return and median excess return (1y and 2y) will be stored with the batting average and shown on upkeep proposals. The report already prints median excess for authors computed in this run. Those stats columns are not stored yet.

## 10. Write the report

Build `state/scored.json` (do not invent fields you did not verify):

```json
{
  "window": ["YYYY-MM-DD", "YYYY-MM-DD"],
  "stats": {
    "sourced": 0,
    "read": 0,
    "scored": 0,
    "passed": 0,
    "tickers": 0,
    "by_type": {"substack": 0},
    "unreachable": [],
    "drops": {"paywalled": 0},
    "sa_skipped_unread": 0
  },
  "ambiguous": [],
  "articles": [
    {
      "sym": "TICKER",
      "title": "",
      "url": "https://...",
      "date": "YYYY-MM-DD",
      "source": "Author",
      "sc": [1, 1, 1, 0.75, 1, 0.5],
      "note": "one line on the variant",
      "notes": {"fact": "", "guidance": "", "balance": "", "soft": ""},
      "ba": "",
      "bat_line": "",
      "since_publish": ""
    }
  ],
  "batting": {}
}
```

Leave `ba`, `bat_line`, and `since_publish` empty to have the report fill them from `state/batting.json` and Yahoo (`--prices`). Set them only when you already computed them.

One-pagers go in `state/onepagers.json`, keyed by ticker: `company`, `words`, `read`, `long`, `c1`–`c6`, `flags` (list), optional `thin`. Model the prose on `reports/2026-10-14/onepagers.json` (the Nyxoah page is the style sample: score, linked article, author, date, length, long disclosure, batting line, each criterion in 1–3 sentences, then red flags).

```bash
python3 scripts/make_report.py --prices --pdf
```

That writes `reports/<today>/REPORT.md`, `articles.csv`, and `REPORT.pdf`. The PDF is the Markdown converted in full, so **Articles from top-record authors** is in both. `--pdf` needs `markdown` and `weasyprint` (`pip install markdown weasyprint`). If those imports fail, the script keeps the Markdown and prints that the PDF was skipped. Confirm `REPORT.md` exists before you tell the user the run is done, and confirm `REPORT.pdf` when the PDF step printed its path.

After the next-six list, the report has **Articles from top-record authors**. `scripts/make_report.py` builds it from `state/source_stats.csv` at report time: every active source whose stored 2-year `ba2y_p_lt_hits` is at least 0.5 on at least 2 pitches. Next to the author, show hits/pitches, the batting average, and that chance. Under each author, list every article in the report window (from `state/seen_posts.csv`, plus any scored article in this run) with title, date, link, and the /6 score when the article was scored. Authors are ordered by `ba2y_p_lt_hits`, highest first. Do not keep a hand list of these authors. An approved `--apply` add stores the recomputed batting average, so the next report includes that author.

Rank by score. Best article per ticker. Top list = top 15 plus every tie at the 15th score, numbered 1..N, ties alphabetical by ticker. The next six sit under the ranked list.

Remove scored URLs from `state/backlog.json` if that file exists.

A full 4-month rebuild, when asked, is `python3 scripts/rerun_sweep.py`, then `rerun/fetch.py`, `rerun/screen1.py`, `rerun/resolve.py`, a full read recorded in `rerun/dispo.py`, then `python3 scripts/make_report.py --legacy`.

## 11. Source upkeep

Do this after the report is written. Runs are on request, so the rules use dates and run counts, not a calendar schedule. Seeking Alpha is not a tracked source. Leave the weekly Seeking Alpha pull as it is. Do not put Seeking Alpha authors in `state/source_stats.csv`.

```bash
python3 scripts/source_upkeep.py --plan
```

That refreshes `state/source_stats.csv` and writes `reports/source_upkeep_<date>.json`. It leaves `config/sources.csv`, `config/sources_dormant_or_dead.csv`, and `config/sources_dropped_never_readd.csv` unchanged. It does not recompute every batting average. A stored average has no expiry. It is recalculated only for a removal proposal or an add candidate, and only when `ba_updated` is not today. `--full-ba` is the resumable pass (saves every 10 authors; `--force` redoes them; `--ba-limit N` bounds it).

Stats per tracked source: last post date, consecutive failed loads, articles scored in the last 6 months, average score over those articles, the 2-year batting average with its pitch count, `ba2y_p_lt_hits` (`p_lt_hits_by_chance`), `ba_updated`, `ba_method`, exclusion counts, price-loss counts, and how many of those pitches were detected from the title versus the body. A blank percentage is neither a drop nor an add. `--crawl` fetches Substack recommendations (same walk as `scripts/crawl_sources.py`) of authors who scored at least 4.5/6. A recommendation is kept only when the publication name or description reads as stock research. Crypto, bitcoin, forex, options trading, day trading, real estate, macro-only, and politics are skipped and are not add candidates. Anyone on the never-readd list is skipped.

Show every proposal to David before changing the list. Each line has the source name, whether it is a drop or an add, the reason, the numbers behind it, `p_lt_hits_by_chance`, and `ba_updated`. Apply only the entries David approves. Set `"approved": true` on those entries, then:

```bash
python3 scripts/source_upkeep.py --apply reports/source_upkeep_<date>.json
```

Approved drops move that row to `config/sources_dormant_or_dead.csv` and append `name`, `url`, `dropped_on`, and `reason` to `config/sources_dropped_never_readd.csv`. Approved adds append a row to `config/sources.csv` and write the batting average computed for that candidate into `state/source_stats.csv`. `--apply` prints `REFUSED` and does not add anyone already on the never-readd list. A dormant recheck must not reactivate a never-readd author. An author who is only on the dormant list is skipped as an automatic add and may be put back by a dormant recheck. Unapproved entries stay as proposals. Every proposal line shows `ba2y_p_lt_hits` and `ba_updated`.

Rules:

- Soft cap: 600 tracked active sources. Only if the list would be over 600 after the rule drops and after counting proposed adds, propose dropping the lowest average score over the last 6 months, and only among sources with at least 3 scored articles in that window, until the list fits.
- Drop when the 2-year batting average is 33% or less on at least 5 pitches. The cutoff is a fraction under 0.334, so a one-third record is included.
- Drop when the last known article is older than 6 months. A blank last-post date stays.
- Drop when the feed failed to load on 4 consecutive runs. A run counts only when `weekly_sweep.py` recorded that source in its stats file. The fourth failure is enough. There is no probation.
- A source that produced no scored articles stays.
- Add a source only when it is a Substack recommendation of an author who scored at least 4.5/6, the publication reads as stock research, the candidate's `ba2y_p_lt_hits` is greater than 0.23, `ba2y_median_excess` is greater than 0, and the author is not on the never-readd list. A missing chance or a missing median excess does not pass.
- David can approve a hand add that misses that bar. Three were added on 2026-10-16 and stay active: Intrinsic Value System (https://intrinsicvaluesystem.substack.com, 15/31, `p_lt_hits_by_chance` 0.3601), Welfare Capital Research (https://welfarecapital.substack.com, 2/2, 0.75), and The Lead-Lag Report (https://leadlagreport.substack.com, 2/2, 0.75). Each `how_discovered` records the exception. Later drops still use the rules above.
- Median stock return and median excess return for the 1-year and 2-year windows will be stored with the batting average and shown on these proposals. Those columns are not in the stats file yet.

## 12. What to tell the user

Lead with:

- articles sourced, articles read in full, articles scored
- the path to `REPORT.md`
- how many Seeking Alpha articles were skipped because the full text could not be read
- sources that could not be reached
- the source-upkeep proposals (name, drop or add, reason, numbers, `p_lt_hits_by_chance`, and `ba_updated`), and that nothing was added or removed until David approves
- one line when nothing cleared the screen

The ranked list and the one-pagers are the product. Do not dump every dropped title in the chat.
