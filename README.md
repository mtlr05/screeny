# Screeny

On-demand stock-article scout. It sweeps Substack and a short list of blogs, forums, Value Investors Club, and Seeking Alpha, reads pitches in full, scores them out of 7, and writes a ranked Markdown report. A total still stored on the old six-point rubric is marked /6.

David runs it from the Cursor agent window. A run starts when someone asks. Nothing runs on a timer. Seeking Alpha is the only step that uses a signed-in browser. No password or cookie is stored in the repo.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Commands assume the repo root. Scripts find `config/`, `state/`, and `reports/` from their own location. `requirements.txt` includes matplotlib, which the report uses for the score chart.

Optional: set `SCREENY_USER_AGENT` if you want a specific User-Agent. The default is a plain browser string. Do not put an email address in the repo.

Fetched article text is copied to a shared folder outside the clone so a fresh checkout can reuse it. Set `SCREENY_TEXT_STORE` to choose the folder. The default is `~/.screeny/fulltext_store`. Before a fetch, scripts look in `fulltext/` and then that store. A usable store file is copied into `fulltext/` and not downloaded again. A bot-check page or an empty file is not usable.

```bash
python3 scripts/text_store.py import fulltext
python3 scripts/text_store.py self-test
```

Markdown is the report. The PDF is that same file, including the chart and **Articles from top-record authors**. Install the optional packages, then pass `--pdf`:

```bash
pip install markdown weasyprint
python3 scripts/make_report.py --pdf
```

That writes `REPORT.pdf` next to `REPORT.md`. If those packages are missing, the script keeps the Markdown and prints that the PDF was skipped. If matplotlib is missing, the script keeps the report and prints that the chart was skipped.

## Run it

- `Run the stock screen`
- `Screen this week's articles`
- `Screen articles since 2026-10-01`
- `What is this author's batting average?`

The agent follows `AGENTS.md` and `.cursor/skills/`. A full run covers the last 4 months. "This week" means the last 7 days.

## What the report contains

`python3 scripts/make_report.py` writes `reports/<today>/REPORT.md`. `--pdf` writes `REPORT.pdf` from that Markdown.

1. **Stats.** Articles sourced, articles read in full, articles scored.
2. **Screening and scoring rules.**
3. **Ranked list.** Best article per ticker. Top 15 plus every tie at the 15th score. The **BA 2y (1y)** column is the author's 2-year batting average as hits/n = %, else the 1-year figure tagged `(1y)`, else `n/a`. It does not change the /7 score.
4. **Score vs P(fewer hits).** One point per scored article. The vertical axis is `P(X < hits)`, defined in the batting-average section below. Blue is the 2-year sample. Red is the 1-year sample, used only when the 2-year sample is missing. A black `x` at 0 means neither sample exists. The image is `score_vs_ba.png` next to the report.
5. **Author batting top-5**, then the next six, then **Articles from top-record authors**, then caveats. The top-5 tables use the ranked list and the next six, and they need at least 5 pitches. The batting average itself is still calculated for every scored author, so the chart can plot names below that cut.
6. **Appendix: one-pagers.**
7. **Appendix: batting average and P(X < hits).** The short explanation, then every chart point: ticker, score, author, linked article, date, sample (`2y`, `1y`, or `x`), hits/n, and the probability.
8. **Appendix: detailed stats.** Drop reasons, the Seeking Alpha breakdown, and counts by source type.

**Articles from top-record authors** lists every article in the report window from an author whose stored 2-year `ba2y_p_lt_hits` is at least 0.5 on at least 2 pitches. The list is read from `state/source_stats.csv` at report time and limited to URLs still in `config/sources.csv`. Next to the author: hits/pitches, the batting average, and `p_lt_hits_by_chance`. Each article shows the date, title, link, and the score when the article was scored.

## Score

One point each, out of 7. Small or mid cap (under about US$10B) and a US or Canada listing are filters, not points. The evidence rules are in `.cursor/skills/stock-screen-scoring/`.

1. Thesis with a secular runway. Cheap with no growth is 0.5.
2. Return of about 40% a year from the publish-day close to the author's target. 25–40% a year is 0.5. Under 25% is 0.
3. CEO ownership or incentive, from the article or a cited filing only. Nothing stated is 0 and the note says "not stated". `scripts/ceo_stake_grep.py` only lists candidate sentences.
4. Moat. None described is 0, and that is not a drop.
5. Edge. An assertion with no checkable evidence is 0, and that is not a drop.
6. Differential view: why the market is wrong, and why that corrects.
7. A named catalyst dated inside 24 months. Named but undated is 0.5.

The author must disclose a long position. A Buy rating alone, or "may hold" boilerplate, does not count.

## Batting average

The batting average is not part of the /7 score. It answers a different question: of this author's past long pitches, how many beat a small-cap index?

A weekly screen calculates it for every author of an article that was read in full and scored. Pitch collection and the calculation are separate:

```bash
python3 bat/pitches.py subdomain
python3 bat/calc.py --today YYYY-MM-DD --benchmark auto
```

The second command calls `batting_average(pitches, today, window_months=12, duration_months=24, benchmark="auto")` twice: once with a 12-month hold and once with a 24-month hold. Both summaries go to `state/batting.json`. To score one window only, pass `--window-months` and `--duration-months`.

- **window_months** (default 12) is how wide the publication cohort is.
- **duration_months** (default 24) is the hold. The cohort ends on `today - duration`, so the return is finished. That default is pitches from 3 years ago up to 2 years ago, held 24 months.
- Duration 12 with the same 12-month width is the 1-year average: pitches from 2 years ago up to 1 year ago, held 12 months.

One pitch per ticker. Inside a window, the earliest pitch on that ticker is the one that counts. The return is the adjusted close, dividends included. A pitch is a hit when that return is above the benchmark over the same dates. The batting average is `h / n`.

`benchmark` `auto` is **IWM** (Russell 2000) for a US listing, and **XCS.TO** (S&P/TSX SmallCap) for `.TO` and `.V`. `.CN` and `.NE` use IWM. Any other symbol, such as `SPY`, is used for every pitch. The report's since-publish column is a different comparison and stays IWM for US listings and XIC.TO for Canada.

`P(X < hits)` treats each evaluated pitch as a fair coin. `X` is the number of hits in `n` pitches if each pitch beats the benchmark with probability 1/2:

`P(X < h) = sum_{k=0}^{h-1} C(n, k) / 2^n`

`bat/calc.py` `p_lt_hits` computes that and rounds to 4 decimals. It is stored as `p_lt` in `state/batting.json` and as `ba2y_p_lt_hits` in `state/source_stats.csv`. It is 0 when there are no hits, and blank when `n` is missing. It is the chance of fewer hits than this author, not the batting average. A 2-for-2 record is 0.75. A 15-for-31 record is 0.3601, because 15 is close to half of 31. Higher means more coin-flip outcomes had fewer hits than this record. The chart plots this number. The top-5 tables and the source proposals sort by it, highest first.

A sample under 5 pitches is flagged as small and does not rank in the top-5 tables. No pitches in a window is `n/a`.

A short, a sell, or a hold is left out unless the body shows the author owns the shares. A title that names one ticker and has no such signal still counts. Counts by reason are stored in `ba2y_excl`. A symbol with no dot and no price is retried as `SYM.TO`, then `SYM.V`. A timeout is not a delisting and is not cached (`ba2y_lost_px`). Only a real Not Found is cached, for 7 days (`ba2y_lost_notfound`). Known buyouts live in the `BUY` map in `bat/calc.py`.

New calculations are tagged `ba_method=v3-iwm-xcs`. A stored row keeps its older tag, including `v2-excl-TO`, until that author is recalculated. A stored average has no expiry. `--plan` recalculates it only for a removal proposal or an add candidate, and only when `ba_updated` is not today. `--full-ba` is the resumable pass over every Substack author (saves every 10; `--force` redoes the current method; `--ba-limit N` stops early). A partial result past the author budget of about 300 seconds is not saved.

The 2-year median excess return is stored as `ba2y_median_excess` (stock return minus benchmark return). The 2-year median stock return is stored as `ba2y_med_ret`. The 1-year median return and the 1-year median excess are not stored yet. The report still prints median excess for authors calculated in the run.

### How a pitch is detected

`python3 bat/pitches.py subdomain` reads the public archive.

- A title that names exactly one US or Canada ticker is method `title`. A dual listing such as `(TSXV: SUM or OTC: SUMMF)` is one company.
- No ticker, or more than one company: fetch `https://<host>/api/v1/posts/<slug>`, cached under `cache/`. Method `body`. The 2-year pass fetches the body even when the title already names the ticker, so a hold or short in the body is visible.
- Seeking Alpha past pitches use the public author API only (`python3 bat/sa_one.py "Author Name" author-slug`). Title, date, ticker, and sentiment are enough. If that API returns a bot check, stop.

## Sources

The active list is `config/sources.csv`. The sweep and the report read that file. They do not change it. After the report, the stock-screen skill runs `python3 scripts/source_upkeep.py --plan`. That refreshes `state/source_stats.csv` and writes `reports/source_upkeep_<date>.json`. It does not change the source lists, and it does not recompute every batting average. `--apply` changes the lists only for proposals marked `"approved": true`.

```mermaid
flowchart TD
  ask["The user asks the agent to run the stock screen"]
  skill["Agent follows the stock-screen skill"]
  sweep["Sweep, read, and score config/sources.csv"]
  report["Write REPORT.md and REPORT.pdf"]
  planNode["After the report, the skill runs source_upkeep.py --plan"]
  ask --> skill --> sweep --> report --> planNode

  sa{"Seeking Alpha row?"}
  planNode --> sa
  sa -->|yes| untracked["Left out of source_stats. List unchanged"]
  sa -->|no| stats["Refresh source_stats.csv and write a proposal"]

  drop{"Removal rule?"}
  stats --> drop
  drop -->|"2y BA at or under 33% on 5+ pitches"| dropProp["Drop proposal"]
  drop -->|"Known last post older than 6 months"| dropProp
  drop -->|"Feed failed 4 runs in a row"| dropProp
  drop -->|none| kept["No drop. No scored articles is not a reason"]

  cap{"Still over 600 after those drops and proposed adds?"}
  kept --> cap
  cap -->|yes| trim["Cap proposal: lowest 6-month score, 3+ scored articles"]
  cap -->|no| remain["Keep"]
  trim --> dropProp

  auto["Automatic add search in the same --plan"]
  stats --> auto
  high["Recommendation of an author who scored at least 5.25/7"]
  auto --> high
  stock{"Publication reads as stock research?"}
  high --> stock
  stock -->|no| skipTopic["Not a candidate"]
  stock -->|yes| known{"Already active, dormant, or on never-readd?"}
  known -->|yes| skipKnown["Skipped"]
  known -->|no| bar{"p > 0.23 and median excess 2y > 0?"}
  bar -->|no| notAdded["Not added"]
  bar -->|yes| addProp["Add proposal"]

  approve{"The user sets approved true?"}
  dropProp --> approve
  addProp --> approve
  approve -->|no| unchanged["sources.csv unchanged"]
  approve -->|drop| parked["--apply moves the row to dormant and appends never-readd"]
  approve -->|add| applied["--apply appends the row and stores its BA"]

  hand["The user adds a row to sources.csv by hand"]
  handCheck{"On the never-readd list?"}
  hand --> handCheck
  handCheck -->|yes| handNo["Not added. Only a hand edit of that file overrides it"]
  handCheck -->|no| handYes["On the active list. The p and median-excess bar does not apply"]
```

Show every proposal before changing the list: source name, drop or add, reason, the numbers, `p_lt_hits_by_chance`, and `ba_updated`. `p_lt_hits_by_chance` is the probability in the batting-average section.

```bash
python3 scripts/source_upkeep.py --apply reports/source_upkeep_YYYY-MM-DD.json
```

An approved drop moves the row to `config/sources_dormant_or_dead.csv` and appends `name`, `url`, `dropped_on`, and `reason` to `config/sources_dropped_never_readd.csv`. An approved add appends a Substack row and writes that candidate's batting average into `state/source_stats.csv`. `--apply` prints `REFUSED` and does not add anyone already on the never-readd list.

### Drops

Tracked active sources have a soft cap of 600. Seeking Alpha is not in that count. Propose a drop only when:

- The stored 2-year batting average is 33% or less on at least 5 pitches. The cutoff is a fraction under 0.334, so one third is included.
- The last known post is older than 6 months. A blank date stays.
- The feed failed to load on 4 consecutive runs. The fourth failure is enough. There is no probation.

A source with no scored articles stays. The cap trim runs only when the list would still exceed 600 after those drops and after counting proposed adds. It proposes the lowest 6-month average score among sources with at least 3 scored articles in that window.

### Adds

An automatic add is a Substack recommendation of an author who scored at least 5.25/7 (4.5/6 when the stored total is still out of 6), the publication reads as stock research, `ba2y_p_lt_hits` is greater than 0.23, and `ba2y_median_excess` is greater than 0. A missing chance or a missing median excess does not pass. Crypto, bitcoin, forex, options trading, day trading, real estate, macro-only, and politics are skipped. Anyone on the dormant list or the never-readd list is skipped. `--crawl` fetches recommendations. Without it, `--plan` uses `cache/crawl.json` when that file exists.

`config/sources_dropped_never_readd.csv` holds authors removed by an approved drop, including the 17 drops from 2026-10-16. Discovery skips them. A dormant recheck must not put them back. The only override is a hand edit of that file. An author who is only on the dormant list can come back through a dormant recheck.

David approved three hand-adds on 2026-10-16 that miss the automatic bar. Later removal proposals still use the drop rules. Their seeded averages were stored with `ba_method=v2-excl-TO` and are not recomputed until that author is recalculated.

| Source | URL | 2y BA | p_lt_hits_by_chance |
|---|---|---|---|
| Intrinsic Value System | https://intrinsicvaluesystem.substack.com | 15/31 | 0.3601 |
| Welfare Capital Research | https://welfarecapital.substack.com | 2/2 | 0.75 |
| The Lead-Lag Report | https://leadlagreport.substack.com | 2/2 | 0.75 |

### What each tracked source stores

Seeking Alpha is excluded. Every other active source records last post date, consecutive failed loads, articles scored in the last 6 months and the average of those scores, the 2-year batting average (`ba2y_hits`, `ba2y_n`, `ba2y_pct`, and `ba_2y` as a percent), `ba2y_p_lt_hits`, `ba2y_median_excess`, `ba2y_med_ret`, `ba_updated`, `ba_method`, title versus body pitch counts, `ba2y_excl`, and `ba2y_lost_px` versus `ba2y_lost_notfound`. A blank percentage is neither a drop nor an add.

Seeking Alpha is one pull for the run. Those articles are not added to `state/seen_posts.csv`. The pull uses the machine's signed-in browser: save the Long Ideas list, run `scripts/sa_ingest.py screen`, read each candidate into `fulltext/sa_<id>.txt`, then `check` and `merge`. If the session has expired, ask the user to sign in. A preview or a missing long disclosure is not scored. A bot check is tried once more, then the pull stops. The unread remainder stays in `reports/sa_read_order_<date>.csv`. `sa_ingest.py resume` continues it.

## Commands and files

```bash
python3 scripts/weekly_sweep.py --since 2026-10-08
python3 scripts/earnings_drops.py
python3 scripts/rss.py FEED_URL --since 2026-10-08
python3 scripts/grab_fulltext.py reports/triage_YYYY-MM-DD.json
python3 scripts/px.py 2026-10-01 AAPL
python3 scripts/sa_ingest.py screen reports/sa_list_YYYY-MM-DD.csv
python3 scripts/sa_ingest.py check fulltext/sa_ID.txt
python3 scripts/sa_ingest.py merge reports/sa_candidates_YYYY-MM-DD.csv reports/triage_YYYY-MM-DD.json
python3 scripts/sa_ingest.py self-test
python3 scripts/ceo_stake_grep.py self-test
python3 scripts/ceo_stake_grep.py FILE
python3 scripts/sa_public.py article https://seekingalpha.com/article/123
python3 bat/sa_one.py "Author Name" author-slug
python3 bat/pitches.py subdomain --limit 20
python3 bat/calc.py --today YYYY-MM-DD --window-months 12 --duration-months 24 --benchmark auto
python3 scripts/make_report.py --prices --pdf
python3 scripts/make_report.py --example --pdf
python3 scripts/crawl_sources.py
python3 scripts/source_upkeep.py --plan
python3 scripts/source_upkeep.py --plan --crawl
python3 scripts/source_upkeep.py --plan --full-ba
python3 scripts/source_upkeep.py --apply reports/source_upkeep_YYYY-MM-DD.json
```

`make_report.py --example` re-renders the 2026-10-14 sample from `examples/scored.json` into `cache/example-REPORT.md`. It does not call the network.

`weekly_sweep.py` drops a free post on the title only when it is a recap, a macro phrase, or a list. Macro matches as a phrase, not as the bare word. A title that names one ticker or one exchange is not dropped on the title. The body screen then reads about the first 1,500 words and drops the post only when that text is clearly not a single-stock pitch, or the author is short, selling, or on hold. Unclear posts stay. Paywalled posts are dropped. Every post in the window is a row in `reports/substack_screen_<date>.csv`.

A full 4-month rebuild, when asked, is `python3 scripts/rerun_sweep.py`, then `rerun/fetch.py`, `rerun/screen1.py`, `rerun/resolve.py`, a full read recorded in `rerun/dispo.py`, then `python3 scripts/make_report.py --legacy`.

| Path | Role |
|---|---|
| `config/sources.csv` | Active sources |
| `config/sources_dormant_or_dead.csv` | Parked feeds. Automatic adds skip them. A dormant recheck may put a parked author back unless they are on the never-readd list |
| `config/sources_dropped_never_readd.csv` | Authors removed by an approved drop. Discovery skips them. `--apply` refuses the add |
| `config/universe.csv` | Optional ticker list for the earnings-drop search |
| `state/seen_posts.csv` | URLs already swept. Dedupe key is `url`. Append-only |
| `state/source_stats.csv` | Per-source upkeep stats. Seeking Alpha is excluded |
| `state/scored.json`, `state/batting.json` | This run's scores and batting averages |
| `state/sa_breakdown.json` | Seeking Alpha counts observed this run |
| `state/sa_results.json` | Seeking Alpha article ids already checked. Gitignored |
| `reports/` | Dated reports and upkeep proposals |
| `examples/` | The 2026-10-14 sample, plus `scored.json` so the report script can re-render it |
| `fulltext/`, `cache/` | Local fetches. Gitignored. Usable texts are also copied to the text store |
| `scripts/` | Sweep, fetch, prices, earnings drops, report, source upkeep |
| `rerun/` | Full 4-month rebuild helpers |
| `bat/` | Author batting average: detection, exclusion, prices, and the chance calculation |
| `.cursor/skills/stock-screen/` | Sweep, triage, read, score, report, then upkeep |
| `.cursor/skills/stock-screen-scoring/` | The seven criteria and the evidence rules |
| `.cursor/skills/author-batting-average/` | Batting average on its own |

| File | Role |
|---|---|
| `bat/pitches.py` | Detect one author's pitches, or write `bat/pitches.json` |
| `bat/lib.py` | Archive, title and body detection, `.TO`/`.V` retry, and the priced score |
| `bat/longcheck.py` | Drop a short, a sell, or a hold whose body does not show ownership |
| `bat/calc.py` | `batting_average(today, window_months, duration_months, benchmark)` and `state/batting.json` |
| `bat/sa_one.py`, `bat/sa.py` | Seeking Alpha public author history |
| `bat/prices.py`, `bat/arch.py` | Price and archive helpers |

## Rules that do not change

Cite every source. Never invent a number, a ticker, a date, or a URL. Score only articles read in full. Do not bypass a paywall or a bot check. Never use Seeking Alpha investing groups. If Seeking Alpha shows a bot check, pause and try that article once more. If it fails again, stop gathering and score what was already read. The author has to disclose a long position. X links are optional and are pasted by hand. This repo does not call the X MCP.
